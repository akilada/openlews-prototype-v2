"""
Amazon Bedrock Client for LLM Reasoning

Functions:
- Uses Bedrock Converse API (model-agnostic messages interface).
- Defaults to cost-saving + generous limits: Claude 3 Haiku.
- Adds throttling backoff + retries.
"""

import json
import os
import random
import time
from typing import Dict, Optional, List

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from aws_lambda_powertools import Logger

logger = Logger(child=True)


class BedrockClient:
    """
    Client for Amazon Bedrock LLM integration.
    """

    DEFAULT_MODEL_ID = os.environ.get(
        "BEDROCK_MODEL_ID",
        "anthropic.claude-3-haiku-20240307-v1:0",
    )

    DEFAULT_REGION = os.environ.get(
        "BEDROCK_REGION", os.environ.get("AWS_REGION", "ap-southeast-2")
    )

    SYSTEM_PROMPT = """You are a Senior Geotechnical Engineer at Sri Lanka's National Building Research Organisation (NBRO), specializing in landslide early warning systems.

Your expertise includes:
- Mohr-Coulomb failure criteria and unsaturated soil mechanics
- NBRO landslide hazard zonation methodology
- Forensic analysis of major Sri Lankan landslides (Aranayake 2016, Meeriyabedda 2014)
- Multi-sensor data fusion and spatial correlation analysis

Your role:
1. Analyze IoT sensor telemetry data for landslide precursors
2. Assess risk using soil mechanics principles and geological context
3. Generate clear, actionable warnings for disaster management officials

Guidelines:
- Use technical accuracy but clear language
- Reference NBRO rainfall thresholds (75/100/150mm for Yellow/Orange/Red alerts)
- Consider spatial correlation (multiple sensors > single sensor)
- Weight geological context from hazard zones heavily
- Be decisive but acknowledge uncertainty
- Output ONLY valid JSON (no markdown, no code blocks)"""

    RISK_ASSESSMENT_TEMPLATE = """SENSOR DATA ANALYSIS REQUEST

{detection_type}

CURRENT READINGS:
{telemetry_summary}

SPATIAL CONTEXT:
{spatial_context}

TEMPORAL TREND (last 24h):
{temporal_trend}

GEOLOGICAL CONTEXT (from Hazard Zonation):
{rag_context}

TASK:
Assess landslide risk based on the above data. Consider:
1. Does sensor data exceed site-specific geological thresholds?
2. Is spatial correlation strong (multiple sensors agreeing)?
3. Are trends accelerating (increasing moisture, tilt velocity)?
4. Does this match known pre-failure patterns (Aranayake, Meeriyabedda)?

OUTPUT FORMAT (JSON only, no markdown):
{{
  "risk_level": "Yellow|Orange|Red",
  "confidence": 0.0-1.0,
  "reasoning": "Technical explanation in 2-3 sentences referencing specific data",
  "trigger_factors": ["factor1", "factor2", "factor3"],
  "recommended_action": "Choose ONE: 'Monitor closely', 'Prepare evacuation', 'Evacuate immediately', 'Restrict access to slope area'",
  "time_to_failure_estimate": "hours|days|unknown",
  "references": ["Aranayake 2016|Meeriyabedda 2014|NBRO threshold|other"]
}}"""

    NARRATIVE_TEMPLATE = """Generate an urgent evacuation alert for local disaster management officials and affected communities.

CONTEXT:
- Risk Level: {risk_level}
- Confidence: {confidence}
- Technical Reasoning: {reasoning}
- Location: {location_description}
- Affected Population: {estimated_population}
- Time to Potential Failure: {time_to_failure}

REQUIREMENTS:
- Length: 150-200 words
- Tone: Urgent and authoritative, but avoid panic
- Language: Simple English (avoid technical jargon)
- Structure: SITUATION → RISK → ACTION → CONTACT

FORMAT:
Use this exact structure:

URGENT LANDSLIDE WARNING - [Location Name]

SITUATION: [What sensors and observations show, in plain language]

RISK: [Probability and timeframe of failure]

ACTION REQUIRED: [Specific, clear evacuation or safety instructions with landmarks]

ISSUED: [Current timestamp]
CONTACT: NBRO Emergency Hotline 117

Keep it concise and actionable."""

    def __init__(
        self, model_id: Optional[str] = None, region_name: Optional[str] = None
    ):
        self.model_id = model_id or self.DEFAULT_MODEL_ID
        self.region_name = region_name or self.DEFAULT_REGION

        # Standard retry config (covers some transient errors)
        cfg = Config(
            region_name=self.region_name,
            retries={
                "max_attempts": int(os.environ.get("BEDROCK_BOTO_RETRIES", "5")),
                "mode": "standard",
            },
        )

        self.client = boto3.client(
            "bedrock-runtime", region_name=self.region_name, config=cfg
        )
        logger.info(
            "Initialized BedrockClient",
            extra={"model_id": self.model_id, "region": self.region_name},
        )

    async def assess_risk(self, detection_input: Dict) -> Dict:
        logger.info(
            "Requesting LLM risk assessment",
            extra={
                "type": detection_input.get("type"),
                "risk_score": detection_input.get("avg_risk")
                or detection_input.get("risk_score"),
            },
        )

        prompt = self._build_risk_assessment_prompt(detection_input)
        response_text = await self._invoke_bedrock(prompt, expect_json=True)

        try:
            assessment = json.loads(response_text)

            required_fields = [
                "risk_level",
                "confidence",
                "reasoning",
                "recommended_action",
            ]
            for f in required_fields:
                if f not in assessment:
                    raise ValueError(f"Missing required field: {f}")

            logger.info(
                "LLM risk assessment received",
                extra={
                    "risk_level": assessment["risk_level"],
                    "confidence": assessment["confidence"],
                },
            )
            return assessment

        except json.JSONDecodeError as e:
            logger.error(
                "Failed to parse LLM response as JSON",
                extra={"error": str(e), "raw": response_text[:2000]},
            )
            raise

    async def generate_narrative(
        self, risk_assessment: Dict, detection_data: Dict, rag_context: Dict
    ) -> str:
        logger.info(
            "Generating alert narrative",
            extra={"risk_level": risk_assessment.get("risk_level")},
        )
        prompt = self._build_narrative_prompt(
            risk_assessment, detection_data, rag_context
        )
        text = await self._invoke_bedrock(prompt, expect_json=False)
        return text.strip()

    def _build_risk_assessment_prompt(self, detection_input: Dict) -> str:
        telemetry = detection_input["telemetry"]
        rag_context = detection_input.get("rag_context", {}) or {}

        if detection_input.get("type") == "cluster":
            detection_type = (
                f"CLUSTER DETECTION ({detection_input['cluster_size']} sensors)\n"
                f"Center Sensor: {detection_input['center_sensor']}\n"
                f"Members: {', '.join(detection_input['members'])}\n"
                f"Average Risk Score: {detection_input['avg_risk']:.2f}"
            )
        else:
            detection_type = (
                "INDIVIDUAL SENSOR DETECTION\n"
                f"Sensor ID: {detection_input.get('sensor_id')}\n"
                f"Risk Score: {detection_input.get('risk_score', 0.0):.2f}"
            )

        telemetry_summary = (
            f"- Location: {telemetry.get('latitude', 0.0):.4f}, {telemetry.get('longitude', 0.0):.4f}\n"
            f"- Soil Moisture: {telemetry.get('moisture_percent', 0):.1f}% (Critical threshold: {telemetry.get('critical_moisture_percent', 40):.1f}%)\n"
            f"- Tilt Rate: {telemetry.get('tilt_rate_mm_hr', 0):.2f} mm/hr\n"
            f"- Vibration Events: {telemetry.get('vibration_count', 0)}/hr (Baseline: {telemetry.get('vibration_baseline', 5)})\n"
            f"- Pore Pressure: {telemetry.get('pore_pressure_kpa', 0):.1f} kPa\n"
            f"- Safety Factor: {telemetry.get('safety_factor', 2.0):.2f}\n"
            f"- 24h Rainfall: {telemetry.get('rainfall_24h_mm', 0):.1f} mm"
        )

        spatial_correlation = float(
            detection_input.get("spatial_correlation", 0.0) or 0.0
        )
        if detection_input.get("type") == "cluster":
            spatial_context = (
                f"- Cluster Size: {detection_input['cluster_size']} sensors within ~50m\n"
                f"- Spatial Correlation: {spatial_correlation:.2f}\n"
                f"- This is a MULTI-SENSOR event (high confidence)"
            )
        else:
            if spatial_correlation > 0.6:
                note = "High agreement with neighbours"
            elif spatial_correlation < 0.3:
                note = "Isolated anomaly (possible sensor fault)"
            else:
                note = "Moderate agreement"
            spatial_context = (
                f"- Spatial Correlation: {spatial_correlation:.2f}\n- {note}"
            )

        moisture_trend = float(telemetry.get("moisture_trend_pct_hr", 0) or 0.0)
        tilt_trend = float(telemetry.get("tilt_acceleration_mm_hr2", 0) or 0.0)
        temporal_trend = (
            f"- Moisture Trend: {moisture_trend:+.2f} %/hr ({'Rising' if moisture_trend > 0 else 'Stable' if moisture_trend == 0 else 'Falling'})\n"
            f"- Tilt Acceleration: {tilt_trend:+.2f} mm/hr² ({'Accelerating' if tilt_trend > 0.1 else 'Stable'})"
        )

        rag_summary = (
            f"- Hazard Level: {rag_context.get('hazard_level', 'Unknown')}\n"
            f"- Soil Type: {rag_context.get('soil_type', 'Unknown')}\n"
            f"- Slope Angle: {rag_context.get('slope_angle', 'Unknown')}°\n"
            f"- Land Use: {rag_context.get('land_use', 'Unknown')}\n"
            f"- Distance to Nearest Hazard Zone: {rag_context.get('distance_m', rag_context.get('distance_meters', 'Unknown'))} m\n"
            f"- Historical Landslides in Area: {rag_context.get('historical_count', 0)}"
        )

        return self.RISK_ASSESSMENT_TEMPLATE.format(
            detection_type=detection_type,
            telemetry_summary=telemetry_summary,
            spatial_context=spatial_context,
            temporal_trend=temporal_trend,
            rag_context=rag_summary,
        )

    def _build_narrative_prompt(
        self, risk_assessment: Dict, detection_data: Dict, rag_context: Dict
    ) -> str:
        from datetime import datetime

        loc = detection_data.get("location") or {}
        loc_label = loc.get("location_label") or loc.get("label")

        # Coordinates fallback
        lat = None
        lon = None
        if "latitude" in detection_data and "longitude" in detection_data:
            lat = detection_data.get("latitude")
            lon = detection_data.get("longitude")
        elif detection_data.get("center_location"):
            lat = detection_data["center_location"].get("lat")
            lon = detection_data["center_location"].get("lon")
        elif detection_data.get("telemetry"):
            lat = detection_data["telemetry"].get("latitude")
            lon = detection_data["telemetry"].get("longitude")

        if not loc_label:
            if lat is not None and lon is not None:
                loc_label = f"{float(lat):.5f}, {float(lon):.5f}"
            else:
                loc_label = "Unknown location"

        maps_url = loc.get("google_maps_url")
        if maps_url:
            location_desc = f"{loc_label} (Map: {maps_url})"
        else:
            location_desc = loc_label

        if detection_data.get("cluster_size"):
            estimated_pop = "50-100 people"
        else:
            estimated_pop = "20-50 people"

        prompt = self.NARRATIVE_TEMPLATE.format(
            risk_level=risk_assessment.get("risk_level", "Unknown"),
            confidence=risk_assessment.get("confidence", 0.0),
            reasoning=risk_assessment.get("reasoning", ""),
            location_description=location_desc,
            estimated_population=estimated_pop,
            time_to_failure=risk_assessment.get("time_to_failure_estimate", "unknown"),
        )

        return prompt.replace(
            "[Current timestamp]", datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        )

    async def _invoke_bedrock(self, user_prompt: str, expect_json: bool) -> str:
        """
        Calls Bedrock using the Converse API.
        Adds retry/backoff for throttling.
        """
        max_tokens = int(os.environ.get("BEDROCK_MAX_TOKENS", "2000"))
        temperature = float(os.environ.get("BEDROCK_TEMPERATURE", "0.3"))
        top_p = float(os.environ.get("BEDROCK_TOP_P", "0.9"))

        if expect_json:
            user_prompt = (
                user_prompt
                + "\n\nIMPORTANT: Return ONLY valid JSON. No extra keys, no prose outside JSON."
            )

        messages = [{"role": "user", "content": [{"text": user_prompt}]}]
        system_prompts = [{"text": self.SYSTEM_PROMPT}]

        inference_cfg = {
            "maxTokens": max_tokens,
            "temperature": temperature,
            "topP": top_p,
        }

        # backoff
        max_attempts = int(os.environ.get("BEDROCK_MAX_ATTEMPTS", "6"))
        base_sleep = float(os.environ.get("BEDROCK_BACKOFF_BASE_SEC", "0.6"))

        last_err: Optional[Exception] = None

        for attempt in range(1, max_attempts + 1):
            try:
                resp = self.client.converse(
                    modelId=self.model_id,
                    messages=messages,
                    system=system_prompts,
                    inferenceConfig=inference_cfg,
                )

                usage = resp.get("usage", {})
                logger.info(
                    "Bedrock converse complete",
                    extra={
                        "inputTokens": usage.get("inputTokens", 0),
                        "outputTokens": usage.get("outputTokens", 0),
                        "totalTokens": usage.get("totalTokens", 0),
                        "stopReason": resp.get("stopReason"),
                    },
                )

                # Extract text
                out_msg = resp["output"]["message"]
                parts: List[str] = []
                for block in out_msg.get("content", []):
                    if "text" in block:
                        parts.append(block["text"])
                return "".join(parts).strip()

            except ClientError as e:
                last_err = e
                code = e.response.get("Error", {}).get("Code", "Unknown")
                msg = e.response.get("Error", {}).get("Message", str(e))

                retryable = code in {
                    "ThrottlingException",
                    "TooManyRequestsException",
                    "ServiceUnavailableException",
                    "ModelTimeoutException",
                    "InternalServerException",
                }

                logger.warning(
                    "Bedrock call failed",
                    extra={"attempt": attempt, "code": code, "message": msg},
                )

                if not retryable or attempt == max_attempts:
                    raise

                sleep_s = (base_sleep * (2 ** (attempt - 1))) + random.uniform(0, 0.25)
                time.sleep(min(sleep_s, 10.0))

            except Exception as e:
                last_err = e
                logger.exception(
                    "Bedrock call failed with unexpected error",
                    extra={"attempt": attempt},
                )
                if attempt == max_attempts:
                    raise
                sleep_s = (base_sleep * (2 ** (attempt - 1))) + random.uniform(0, 0.25)
                time.sleep(min(sleep_s, 10.0))

        raise RuntimeError(
            f"Bedrock invocation failed after {max_attempts} attempts: {last_err}"
        )
