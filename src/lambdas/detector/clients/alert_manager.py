"""
Alert Manager

Handles alert lifecycle:
- Creation of new alerts
- Deduplication (avoid duplicate warnings)
- Escalation (Yellow → Orange → Red)
- SNS notification publishing
"""

import json
import time
from datetime import datetime
from typing import Any, Dict, Optional
from decimal import Decimal

from aws_lambda_powertools import Logger

logger = Logger(child=True)


def _dynamodb_sanitise(value: Any) -> Any:
    """
    Recursively sanitise an object for DynamoDB put_item():
    - float -> Decimal(str(float))
    - None values removed from dicts
    - None values removed from lists
    """
    if value is None:
        return None

    if isinstance(value, float):
        return Decimal(str(value))

    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            sv = _dynamodb_sanitise(v)
            if sv is not None:
                out[k] = sv
        return out

    if isinstance(value, list):
        out = []
        for v in value:
            sv = _dynamodb_sanitise(v)
            if sv is not None:
                out.append(sv)
        return out

    return value


def _google_maps_url(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={lat:.6f},{lon:.6f}"


class AlertManager:
    """
    Manages alert creation, deduplication, and escalation.
    """

    RISK_HIERARCHY = {"Yellow": 1, "Orange": 2, "Red": 3}
    ALERT_TTL_SECONDS = 30 * 24 * 3600

    @staticmethod
    def _to_native(x):
        """Convert DynamoDB Decimal to int/float recursively for JSON/SNS."""
        if isinstance(x, Decimal):
            if x == x.to_integral_value():
                return int(x)
            return float(x)
        if isinstance(x, dict):
            return {k: AlertManager._to_native(v) for k, v in x.items()}
        if isinstance(x, list):
            return [AlertManager._to_native(v) for v in x]
        return x

    def __init__(self, dynamodb_resource, alerts_table_name: str, sns_client, sns_topic_arn: str):
        self.table = dynamodb_resource.Table(alerts_table_name)
        self.sns = sns_client
        self.sns_topic_arn = sns_topic_arn
        logger.info("Initialized AlertManager", extra={"table": alerts_table_name})

    def get_active_alert(self, alert_id_prefix: str) -> Optional[Dict]:
        try:
            response = self.table.query(
                IndexName="StatusIndex",
                KeyConditionExpression="#status = :status",
                FilterExpression="begins_with(alert_id, :prefix)",
                ExpressionAttributeNames={"#status": "status"},
                ExpressionAttributeValues={":status": "active", ":prefix": alert_id_prefix},
                ScanIndexForward=False,
                Limit=1,
            )
            if response.get("Items"):
                alert = response["Items"][0]
                logger.info("Found active alert", extra={"alert_id": alert.get("alert_id")})
                return alert
            return None
        except Exception:
            logger.exception("Failed to query active alerts", extra={"prefix": alert_id_prefix})
            return None

    def create_alert(
        self,
        alert_id_prefix: str,
        llm_assessment: Dict,
        detection_data: Dict,
        rag_context: Dict,
        narrative: Optional[str] = None,
        location: Optional[Dict] = None,
    ) -> Dict:
        """
        location (recommended):
          {
            "latitude": float,
            "longitude": float,
            "location_label": str,
            "google_maps_url": str,
            "resolved_by": "amazon_location|coordinates_only|...",
            "address": {...}
          }
        """
        timestamp = int(time.time())
        alert_id = self._generate_alert_id(alert_id_prefix, timestamp)

        is_cluster = bool(detection_data.get("members")) or bool(detection_data.get("size")) or bool(detection_data.get("cluster_size"))
        logger.info(
            "Creating new alert",
            extra={
                "alert_id": alert_id,
                "risk_level": llm_assessment.get("risk_level"),
                "confidence": llm_assessment.get("confidence"),
                "is_cluster": is_cluster,
            },
        )

        # Determine coordinates
        lat = lon = None
        if is_cluster:
            center = detection_data.get("center_location") or {}
            lat = center.get("lat")
            lon = center.get("lon")
        else:
            telem = detection_data.get("telemetry") or {}
            lat = telem.get("latitude")
            lon = telem.get("longitude")

        try:
            lat = float(lat) if lat is not None else None
            lon = float(lon) if lon is not None else None
        except Exception:
            lat = lon = None

        # Build/normalise location object
        loc = location or {}
        if lat is not None and lon is not None:
            loc.setdefault("latitude", lat)
            loc.setdefault("longitude", lon)
            loc.setdefault("google_maps_url", _google_maps_url(lat, lon))
            loc.setdefault("location_label", f"{lat:.5f}, {lon:.5f}")
            loc.setdefault("resolved_by", "coordinates_only")
            loc.setdefault("address", {})

        alert = {
            "alert_id": alert_id,
            "created_at": timestamp,
            "updated_at": timestamp,
            "status": "active",
            "risk_level": llm_assessment["risk_level"],
            "confidence": llm_assessment["confidence"],
            "llm_reasoning": llm_assessment.get("reasoning"),
            "trigger_factors": llm_assessment.get("trigger_factors", []),
            "recommended_action": llm_assessment.get("recommended_action"),
            "time_to_failure": llm_assessment.get("time_to_failure_estimate", "unknown"),
            "references": llm_assessment.get("references", []),
            "narrative_english": narrative,
            "detection_type": "cluster" if is_cluster else "individual",

            "latitude": lat,
            "longitude": lon,
            "google_maps_url": (loc.get("google_maps_url") if isinstance(loc, dict) else None),

            "geological_context": {
                "hazard_level": rag_context.get("hazard_level", "Unknown"),
                "soil_type": rag_context.get("soil_type", "Unknown"),
                "critical_moisture": rag_context.get("critical_moisture_percent", 40),
            },

            "escalation_history": [
                {"timestamp": timestamp, "from_level": "NONE", "to_level": llm_assessment["risk_level"], "reason": "Initial alert"}
            ],

            "location": {
                "label": (loc or {}).get("location_label", "Unknown"),
                "google_maps_url": (loc or {}).get("google_maps_url"),
                "google_maps_directions_url": (loc or {}).get("google_maps_directions_url"),
                "resolved_by": (loc or {}).get("resolved_by", "unknown"),
                "address": (loc or {}).get("address", {}) or {},
                "place": (loc or {}).get("place", {}) or {},
            },

            "ttl": timestamp + self.ALERT_TTL_SECONDS,
        }

        if is_cluster:
            members = detection_data.get("members", [])
            cluster_size = detection_data.get("cluster_size") or detection_data.get("size") or len(members)
            alert["cluster_size"] = int(cluster_size)
            alert["sensors_affected"] = members
            alert["center_location"] = detection_data.get("center_location", {})
            alert["center_sensor"] = detection_data.get("center_sensor", alert_id_prefix)
        else:
            alert["sensor_id"] = detection_data.get("sensor_id", alert_id_prefix)

        alert = _dynamodb_sanitise(alert)
        self.table.put_item(Item=alert)

        self._publish_to_sns(alert)
        return {"action": "created", "alert_id": alert_id, "risk_level": alert.get("risk_level")}

    def escalate_alert(self, existing_alert: Dict, new_assessment: Dict, detection_data: Dict, rag_context: Dict) -> Dict:
        alert_id = existing_alert["alert_id"]
        timestamp = int(time.time())

        old_level = existing_alert["risk_level"]
        new_level = new_assessment["risk_level"]

        logger.info("Escalating alert", extra={"alert_id": alert_id, "from": old_level, "to": new_level})

        escalation_entry = {
            "timestamp": timestamp,
            "from_level": old_level,
            "to_level": new_level,
            "reason": f"Risk level increased. New confidence: {new_assessment['confidence']:.2f}",
        }

        escalation_history = existing_alert.get("escalation_history", [])
        escalation_history.append(escalation_entry)

        self.table.update_item(
            Key={"alert_id": alert_id, "created_at": existing_alert["created_at"]},
            UpdateExpression="""
                SET updated_at = :timestamp,
                    risk_level = :new_level,
                    confidence = :confidence,
                    llm_reasoning = :reasoning,
                    recommended_action = :action,
                    escalation_history = :history
            """,
            ExpressionAttributeValues={
                ":timestamp": timestamp,
                ":new_level": new_level,
                ":confidence": new_assessment["confidence"],
                ":reasoning": new_assessment["reasoning"],
                ":action": new_assessment["recommended_action"],
                ":history": escalation_history,
            },
        )

        updated_alert = existing_alert.copy()
        updated_alert.update(
            {
                "updated_at": timestamp,
                "risk_level": new_level,
                "confidence": new_assessment["confidence"],
                "llm_reasoning": new_assessment["reasoning"],
                "recommended_action": new_assessment["recommended_action"],
                "escalation_history": escalation_history,
            }
        )

        self._publish_to_sns(updated_alert)
        return {"action": "escalated", "alert_id": alert_id, "from_level": old_level, "to_level": new_level}

    def _generate_alert_id(self, prefix: str, timestamp: int) -> str:
        date_str = datetime.utcfromtimestamp(timestamp).strftime("%Y%m%d_%H%M%S")
        return f"ALERT_{date_str}_{prefix}"

    def _publish_to_sns(self, alert: Dict) -> None:
        if not self.sns_topic_arn:
            logger.warning("SNS_TOPIC_ARN not set - skipping SNS publish")
            return

        try:
            subject = f"OpenLEWS {alert.get('risk_level', 'Alert')} - {alert.get('alert_id', '')}"

            payload = {
                "alert_id": alert.get("alert_id"),
                "status": alert.get("status"),
                "risk_level": alert.get("risk_level"),
                "confidence": alert.get("confidence"),
                "recommended_action": alert.get("recommended_action"),
                "time_to_failure": alert.get("time_to_failure"),
                "location": alert.get("location"),
                "google_maps_url": alert.get("google_maps_url"),
                "latitude": alert.get("latitude"),
                "longitude": alert.get("longitude"),
                "geological_context": alert.get("geological_context"),
                "narrative_english": alert.get("narrative_english"),
                "created_at": alert.get("created_at"),
            }

            payload = self._to_native(payload)

            self.sns.publish(
                TopicArn=self.sns_topic_arn,
                Subject=subject[:100],
                Message=json.dumps(payload, ensure_ascii=False, indent=2),
            )

            logger.info("SNS publish succeeded", extra={"alert_id": alert.get("alert_id")})
        except Exception:
            logger.exception("SNS publish failed", extra={"alert_id": alert.get("alert_id")})
