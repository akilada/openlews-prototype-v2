"""
OpenLEWS Detector Lambda - Main Handler

Scheduled analysis of sensor telemetry for landslide risk detection.
Implements multi-modal fusion algorithm with LLM reasoning.

"""

import json
import os
import time
from datetime import datetime
from typing import Dict, List, Optional

import boto3
from aws_lambda_powertools import Logger, Tracer
from aws_lambda_powertools.utilities.typing import LambdaContext

from core.fusion_algorithm import FusionAlgorithm
from core.risk_scorer import RiskScorer
from clients.rag_client import RAGClient
from clients.bedrock_client import BedrockClient
from clients.alert_manager import AlertManager
from utils.telemetry_fetcher import TelemetryFetcher
from utils.location_resolver import LocationResolver

logger = Logger()
tracer = Tracer()

# Initialize clients
dynamodb = boto3.resource("dynamodb")
sns = boto3.client("sns")
lambda_client = boto3.client("lambda")

# Environment variables
TELEMETRY_TABLE = os.environ["TELEMETRY_TABLE_NAME"]
ALERTS_TABLE = os.environ["ALERTS_TABLE_NAME"]
RAG_LAMBDA_ARN = os.environ["RAG_LAMBDA_ARN"]
SNS_TOPIC_ARN = os.environ["SNS_TOPIC_ARN"]
RISK_THRESHOLD = float(os.environ.get("RISK_THRESHOLD", "0.6"))
BEDROCK_MODEL_ID = os.environ.get(
    "BEDROCK_MODEL_ID", "apac.anthropic.claude-3-haiku-20240307-v1:0"
)

# Initialize algorithm components
fusion_algorithm = FusionAlgorithm()
risk_scorer = RiskScorer()
rag_client = RAGClient(lambda_client, RAG_LAMBDA_ARN)
bedrock_client = BedrockClient(BEDROCK_MODEL_ID)
alert_manager = AlertManager(dynamodb, ALERTS_TABLE, sns, SNS_TOPIC_ARN)
telemetry_fetcher = TelemetryFetcher(dynamodb, TELEMETRY_TABLE)
location_resolver = LocationResolver()


@tracer.capture_method
def fetch_recent_telemetry(hours: int = 24) -> Dict[str, List[Dict]]:
    """
    Fetch telemetry data for all sensors from the last N hours.

    Args:
        hours: Number of hours to look back

    Returns:
        Dictionary mapping sensor_id to list of telemetry records
    """
    logger.info(f"Fetching telemetry for last {hours} hours")

    end_time = int(time.time())
    start_time = end_time - (hours * 3600)

    return telemetry_fetcher.fetch_by_time_range(start_time, end_time)


@tracer.capture_method
def analyze_sensors(telemetry_data: Dict[str, List[Dict]]) -> Dict:
    """
    Analyze all sensors and detect clusters.

    Args:
        telemetry_data: Sensor telemetry organized by sensor_id

    Returns:
        Analysis results with risk scores and clusters
    """
    logger.info(f"Analyzing {len(telemetry_data)} sensors")

    # Calculate individual risk scores
    sensor_risks = {}
    for sensor_id, records in telemetry_data.items():
        if not records:
            continue

        latest = records[-1]  # Most recent reading
        risk = risk_scorer.calculate_sensor_risk(latest)
        sensor_risks[sensor_id] = {"risk_score": risk, "telemetry": latest}

    # Calculate spatial correlation
    for sensor_id in sensor_risks:
        correlation = fusion_algorithm.calculate_spatial_correlation(
            sensor_id, sensor_risks, telemetry_data
        )
        sensor_risks[sensor_id]["spatial_correlation"] = correlation

        # Adjust risk based on correlation
        composite_risk = fusion_algorithm.calculate_composite_risk(
            sensor_risks[sensor_id]["risk_score"], correlation
        )
        sensor_risks[sensor_id]["composite_risk"] = composite_risk

    # Detect clusters (3+ sensors in proximity with high risk)
    clusters = fusion_algorithm.detect_clusters(sensor_risks, telemetry_data)

    return {
        "sensor_risks": sensor_risks,
        "clusters": clusters,
        "analysis_timestamp": int(time.time()),
    }


@tracer.capture_method
async def process_high_risk_detections(analysis: Dict) -> List[Dict]:
    """
    Process detections exceeding risk threshold with LLM reasoning.

    Args:
        analysis: Output from analyze_sensors()

    Returns:
        List of alerts created or escalated
    """
    alerts_processed = []

    # Process clusters first (higher priority)
    for cluster in analysis["clusters"]:
        if cluster["avg_risk"] > RISK_THRESHOLD:
            alert = await process_cluster(cluster, analysis)
            if alert:
                alerts_processed.append(alert)

    # Process individual high-risk sensors not in clusters
    for sensor_id, data in analysis["sensor_risks"].items():
        if data["composite_risk"] > RISK_THRESHOLD:
            # Check if already part of a cluster
            in_cluster = any(sensor_id in c["members"] for c in analysis["clusters"])
            if not in_cluster:
                alert = await process_individual_sensor(sensor_id, data, analysis)
                if alert:
                    alerts_processed.append(alert)

    return alerts_processed


@tracer.capture_method
async def process_cluster(cluster: Dict, analysis: Dict) -> Optional[Dict]:
    """
    Process a high-risk cluster with LLM reasoning.

    Args:
        cluster: Cluster detection data
        analysis: Full analysis context

    Returns:
        Alert data if created/escalated, None otherwise
    """
    cluster_id = f"CLUSTER_{cluster['center_sensor']}"

    logger.info(
        f"Processing high-risk cluster: {cluster_id}",
        extra={"cluster_size": cluster["size"], "avg_risk": cluster["avg_risk"]},
    )

    # Get geological context from RAG
    center_location = cluster["center_location"]
    resolved_location = location_resolver.resolve(
        float(center_location["lat"]),
        float(center_location["lon"]),
    )

    rag_context = await rag_client.query_nearest(
        center_location["lat"], center_location["lon"]
    )

    # Prepare data for LLM
    llm_input = prepare_llm_input(cluster, rag_context, analysis, is_cluster=True)

    # Put location context into llm_input so the narrative can use it
    llm_input["location"] = resolved_location

    # Get LLM risk assessment
    llm_output = await bedrock_client.assess_risk(llm_input)

    # Check for existing alert (deduplication)
    existing_alert = alert_manager.get_active_alert(cluster_id)

    if existing_alert:
        # Check if escalation needed
        if should_escalate(existing_alert, llm_output):
            logger.info(f"Escalating alert for {cluster_id}")
            alert = alert_manager.escalate_alert(
                existing_alert, llm_output, cluster, rag_context
            )
            return alert
        else:
            logger.info(f"Alert already active for {cluster_id}, no escalation needed")
            return None
    else:
        # Create new alert
        logger.info(f"Creating new alert for {cluster_id}")

        # Generate narrative if Orange or Red
        narrative = None
        if llm_output["risk_level"] in ["Orange", "Red"]:
            narrative = await bedrock_client.generate_narrative(
                llm_output,
                {
                    **cluster,
                    "location": resolved_location,
                    "latitude": float(center_location["lat"]),
                    "longitude": float(center_location["lon"]),
                },
                rag_context,
            )

        alert = alert_manager.create_alert(
            cluster_id,
            llm_output,
            cluster,
            rag_context,
            narrative,
            location=resolved_location,
        )
        return alert


@tracer.capture_method
async def process_individual_sensor(
    sensor_id: str, sensor_data: Dict, analysis: Dict
) -> Optional[Dict]:
    """
    Process a high-risk individual sensor.

    Args:
        sensor_id: Sensor identifier
        sensor_data: Risk and telemetry data
        analysis: Full analysis context

    Returns:
        Alert data if created/escalated, None otherwise
    """
    logger.info(
        f"Processing high-risk sensor: {sensor_id}",
        extra={"composite_risk": sensor_data["composite_risk"]},
    )

    # Get location from telemetry
    telemetry = sensor_data["telemetry"]
    lat = float(telemetry["latitude"])
    lon = float(telemetry["longitude"])
    resolved_location = location_resolver.resolve(lat, lon)

    # Get geological context from RAG
    rag_context = await rag_client.query_nearest(
        telemetry["latitude"], telemetry["longitude"]
    )

    # Prepare data for LLM
    llm_input = prepare_llm_input(sensor_data, rag_context, analysis, is_cluster=False)

    # Get LLM risk assessment
    llm_output = await bedrock_client.assess_risk(llm_input)

    # Check for existing alert
    existing_alert = alert_manager.get_active_alert(sensor_id)

    if existing_alert:
        if should_escalate(existing_alert, llm_output):
            logger.info(f"Escalating alert for {sensor_id}")
            alert = alert_manager.escalate_alert(
                existing_alert,
                llm_output,
                {"sensor_id": sensor_id, "telemetry": telemetry},
                rag_context,
            )
            return alert
        else:
            return None
    else:
        # Create new alert
        logger.info(f"Creating new alert for {sensor_id}")

        # Generate narrative if Orange or Red
        narrative = None
        if llm_output["risk_level"] in ["Orange", "Red"]:
            narrative = await bedrock_client.generate_narrative(
                llm_output,
                {
                    "sensor_id": sensor_id,
                    "telemetry": telemetry,
                    "location": resolved_location,
                    "latitude": lat,
                    "longitude": lon,
                },
                rag_context,
            )

        resolved_location = location_resolver.resolve(
            float(telemetry["latitude"]), float(telemetry["longitude"])
        )

        alert = alert_manager.create_alert(
            sensor_id,
            llm_output,
            {"sensor_id": sensor_id, "telemetry": telemetry},
            rag_context,
            narrative,
            location=resolved_location,
        )
        return alert


def prepare_llm_input(
    detection_data: Dict, rag_context: Dict, analysis: Dict, is_cluster: bool
) -> Dict:
    """
    Prepare structured input for LLM reasoning.

    Args:
        detection_data: Cluster or sensor data
        rag_context: Geological context from RAG
        analysis: Full analysis context
        is_cluster: Whether this is a cluster or individual sensor

    Returns:
        Structured data for LLM prompt
    """
    if is_cluster:
        # Get telemetry from center sensor
        center_sensor = detection_data["center_sensor"]
        telemetry = analysis["sensor_risks"][center_sensor]["telemetry"]

        return {
            "type": "cluster",
            "cluster_size": detection_data["size"],
            "avg_risk": detection_data["avg_risk"],
            "center_sensor": center_sensor,
            "members": detection_data["members"],
            "telemetry": telemetry,
            "rag_context": rag_context,
            "spatial_correlation": detection_data.get("correlation", 0.0),
        }
    else:
        return {
            "type": "individual",
            "sensor_id": detection_data["telemetry"]["sensor_id"],
            "risk_score": detection_data["composite_risk"],
            "telemetry": detection_data["telemetry"],
            "rag_context": rag_context,
            "spatial_correlation": detection_data.get("spatial_correlation", 0.0),
        }


def should_escalate(existing_alert: Dict, new_assessment: Dict) -> bool:
    """
    Determine if an existing alert should be escalated.

    Args:
        existing_alert: Current alert record
        new_assessment: New LLM assessment

    Returns:
        True if escalation warranted
    """
    risk_hierarchy = {"Yellow": 1, "Orange": 2, "Red": 3}

    current_level = existing_alert["risk_level"]
    new_level = new_assessment["risk_level"]

    # Escalate if risk level increased
    if risk_hierarchy[new_level] > risk_hierarchy[current_level]:
        return True

    # Escalate if confidence significantly increased at same level
    if (
        new_level == current_level
        and new_assessment["confidence"] > existing_alert["confidence"] + 0.15
    ):
        return True

    return False


@logger.inject_lambda_context
@tracer.capture_lambda_handler
def lambda_handler(event: Dict, context: LambdaContext) -> Dict:
    """
    Main Lambda handler for scheduled detection runs.

    Args:
        event: EventBridge scheduled event
        context: Lambda context

    Returns:
        Execution summary
    """
    logger.info(
        "Starting detector analysis",
        extra={"event": event, "risk_threshold": RISK_THRESHOLD},
    )

    start_time = time.time()

    try:
        # Fetch recent telemetry
        telemetry_data = fetch_recent_telemetry(hours=24)

        if not telemetry_data:
            logger.warning("No telemetry data found")
            return {
                "statusCode": 200,
                "body": json.dumps(
                    {"status": "no_data", "message": "No telemetry data available"}
                ),
            }

        # Analyze sensors
        analysis = analyze_sensors(telemetry_data)

        logger.info(
            "Analysis complete",
            extra={
                "sensors_analyzed": len(analysis["sensor_risks"]),
                "clusters_detected": len(analysis["clusters"]),
                "high_risk_count": sum(
                    1
                    for s in analysis["sensor_risks"].values()
                    if s["composite_risk"] > RISK_THRESHOLD
                ),
            },
        )

        # Process high-risk detections (async operations)
        import asyncio

        alerts = asyncio.run(process_high_risk_detections(analysis))

        execution_time = time.time() - start_time

        logger.info(
            "Detection complete",
            extra={
                "alerts_processed": len(alerts),
                "execution_time_seconds": execution_time,
            },
        )

        return {
            "statusCode": 200,
            "body": json.dumps(
                {
                    "status": "success",
                    "sensors_analyzed": len(analysis["sensor_risks"]),
                    "clusters_detected": len(analysis["clusters"]),
                    "alerts_created": sum(
                        1 for a in alerts if a.get("action") == "created"
                    ),
                    "alerts_escalated": sum(
                        1 for a in alerts if a.get("action") == "escalated"
                    ),
                    "execution_time": execution_time,
                    "timestamp": datetime.utcnow().isoformat(),
                }
            ),
        }

    except Exception as e:
        logger.exception("Error in detector lambda")
        return {
            "statusCode": 500,
            "body": json.dumps({"status": "error", "error": str(e)}),
        }
