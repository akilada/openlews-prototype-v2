"""
Telemetry Ingestor Lambda Handler
"""

import json
import os
import boto3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from decimal import Decimal
import logging

from boto3.dynamodb.conditions import Key

logger = logging.getLogger()
logger.setLevel(os.getenv("LOG_LEVEL", "INFO"))

dynamodb = boto3.resource("dynamodb")
eventbridge = boto3.client("events")

TELEMETRY_TABLE = os.getenv("TELEMETRY_TABLE", "")
HAZARD_ZONES_TABLE = os.getenv("HAZARD_ZONES_TABLE", "")
EVENT_BUS = os.getenv("EVENT_BUS", "default")
ENABLE_NSDI_ENRICHMENT = os.getenv("ENABLE_NSDI_ENRICHMENT", "true").lower() == "true"
ENABLE_EVENTBRIDGE = os.getenv("ENABLE_EVENTBRIDGE", "true").lower() == "true"

telemetry_table = dynamodb.Table(TELEMETRY_TABLE)
hazard_zones_table = dynamodb.Table(HAZARD_ZONES_TABLE)


class ValidationError(Exception):
    pass


class TelemetryValidator:
    REQUIRED_FIELDS = [
        "sensor_id",
        "timestamp",
        "latitude",
        "longitude",
        "moisture_percent",
        "geohash",
    ]

    VALIDATION_RULES = {
        "moisture_percent": (0, 100),
        "tilt_x_degrees": (-30, 30),
        "tilt_y_degrees": (-30, 30),
        "pore_pressure_kpa": (-100, 50),
        "battery_percent": (0, 100),
        "temperature_c": (-10, 50),
        "latitude": (-90, 90),
        "longitude": (-180, 180),
        "vibration_count": (0, 1000),
        "safety_factor": (0, 10),
        "tilt_rate_mm_hr": (0, 50),
    }

    @classmethod
    def validate(cls, telemetry: Dict) -> Tuple[bool, Optional[str]]:
        missing_fields = [f for f in cls.REQUIRED_FIELDS if f not in telemetry]
        if missing_fields:
            return False, f"Missing required fields: {', '.join(missing_fields)}"

        timestamp = telemetry.get("timestamp")
        if isinstance(timestamp, str):
            try:
                ts = timestamp.strip()
                if ts.endswith("Z"):
                    ts = ts[:-1] + "+00:00"
                dt = datetime.fromisoformat(ts)
                telemetry["timestamp"] = int(dt.timestamp())
                timestamp = telemetry["timestamp"]
            except Exception:
                return (
                    False,
                    f"timestamp string must be ISO 8601 or Unix epoch number, got {timestamp}",
                )
        elif not isinstance(timestamp, (int, float)):
            return False, f"timestamp must be Unix epoch number, got {type(timestamp)}"

        if timestamp < 1577836800 or timestamp > 2147483647:
            return False, f"timestamp out of valid range: {timestamp}"

        if (
            not isinstance(telemetry["sensor_id"], str)
            or len(telemetry["sensor_id"]) < 3
        ):
            return False, f"Invalid sensor_id: {telemetry.get('sensor_id')}"

        for field, (min_val, max_val) in cls.VALIDATION_RULES.items():
            if field in telemetry:
                value = telemetry[field]
                if not isinstance(value, (int, float)):
                    return False, f"{field} must be numeric, got {type(value)}"
                if not min_val <= value <= max_val:
                    return False, f"{field}={value} out of range [{min_val}, {max_val}]"

        geohash = telemetry.get("geohash", "")
        if not isinstance(geohash, str) or len(geohash) < 4:
            return False, f"Invalid geohash: {geohash}"

        return True, None


# Geohash neighbour support
_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"
_NEIGHBORS = {
    "right": {
        "even": "bc01fg45238967deuvhjyznpkmstqrwx",
        "odd": "p0r21436x8zb9dcf5h7kjnmqesgutwvy",
    },
    "left": {
        "even": "238967debc01fg45kmstqrwxuvhjyznp",
        "odd": "14365h7k9dcfesgujnmqp0r2twvyx8zb",
    },
    "top": {
        "even": "p0r21436x8zb9dcf5h7kjnmqesgutwvy",
        "odd": "bc01fg45238967deuvhjyznpkmstqrwx",
    },
    "bottom": {
        "even": "14365h7k9dcfesgujnmqp0r2twvyx8zb",
        "odd": "238967debc01fg45kmstqrwxuvhjyznp",
    },
}
_BORDERS = {
    "right": {"even": "bcfguvyz", "odd": "prxz"},
    "left": {"even": "0145hjnp", "odd": "028b"},
    "top": {"even": "prxz", "odd": "bcfguvyz"},
    "bottom": {"even": "028b", "odd": "0145hjnp"},
}


def _adjacent(geohash: str, direction: str) -> str:
    if not geohash:
        return ""
    geohash = geohash.lower()
    last = geohash[-1]
    parent = geohash[:-1]
    t = "even" if len(geohash) % 2 == 0 else "odd"

    if last in _BORDERS[direction][t] and parent:
        parent = _adjacent(parent, direction)

    idx = _NEIGHBORS[direction][t].find(last)
    return parent + _BASE32[idx]


def geohash_neighbors_8(geohash6: str) -> List[str]:
    top = _adjacent(geohash6, "top")
    bottom = _adjacent(geohash6, "bottom")
    right = _adjacent(geohash6, "right")
    left = _adjacent(geohash6, "left")

    return list(
        {
            geohash6,
            top,
            bottom,
            right,
            left,
            _adjacent(top, "right"),
            _adjacent(top, "left"),
            _adjacent(bottom, "right"),
            _adjacent(bottom, "left"),
        }
    )


def point_in_bbox(lat: float, lon: float, bbox: Dict) -> bool:
    try:
        return (
            bbox["min_lat"] <= Decimal(str(lat)) <= bbox["max_lat"]
            and bbox["min_lon"] <= Decimal(str(lon)) <= bbox["max_lon"]
        )
    except Exception:
        return False


class NSDIEnricher:
    """
    Enrich telemetry with hazard-zone data.

    Uses existing GeoHashIndex (HASH key = 'geohash'), where hazard zones store
    geohash4 in the 'geohash' attribute.

    Then refines using bounding_box containment.
    """

    HAZARD_RANK = {"Very High": 4, "High": 3, "Moderate": 2, "Low": 1, "Unknown": 0}

    def __init__(self, hazard_table):
        self.table = hazard_table
        self.cache = {}
        self.index_name = os.getenv("HAZARD_GEOHASH_INDEX", "GeoHashIndex")
        self.index_key = os.getenv("HAZARD_GEOHASH_KEY", "geohash")

    @staticmethod
    def _to_float(v):
        if v is None:
            return None
        if isinstance(v, Decimal):
            return float(v)
        return float(v)

    @classmethod
    def _bbox_contains(cls, bbox: dict, lat: float, lon: float) -> bool:
        if not bbox:
            return False

        min_lat = cls._to_float(bbox.get("min_lat"))
        max_lat = cls._to_float(bbox.get("max_lat"))
        min_lon = cls._to_float(bbox.get("min_lon"))
        max_lon = cls._to_float(bbox.get("max_lon"))

        if None in (min_lat, max_lat, min_lon, max_lon):
            return False

        return (min_lat <= lat <= max_lat) and (min_lon <= lon <= max_lon)

    def _pick_best_zone(self, zones: list, lat: float, lon: float) -> dict | None:
        contained = [
            z for z in zones if self._bbox_contains(z.get("bounding_box"), lat, lon)
        ]
        candidates = contained if contained else zones
        if not candidates:
            return None

        def hazard_rank(zone):
            level = zone.get("level") or zone.get("hazard_level") or "Unknown"
            return self.HAZARD_RANK.get(level, 0)

        return sorted(candidates, key=hazard_rank, reverse=True)[0]

    @staticmethod
    def _to_enrichment(zone: dict) -> dict:
        level = zone.get("level") or zone.get("hazard_level") or "Unknown"
        return {
            "hazard_level": level,
            "hazard_zone_id": zone.get("zone_id", "Unknown"),
            "district": zone.get("district", "Unknown"),
            "ds_division": zone.get("ds_division", "Unknown"),
            "gn_division": zone.get("gn_division", "Unknown"),
            "landslide_type": zone.get("landslide_type", "Unknown"),
            "soil_type": zone.get("soil_type", "Unknown"),
        }

    def get_hazard_zone(
        self, geohash: str, latitude: float, longitude: float
    ) -> Optional[Dict]:
        geohash4 = (geohash or "")[:4]
        if len(geohash4) < 4:
            return None

        # cache hit
        zones = self.cache.get(geohash4)
        if zones is None:
            try:
                resp = self.table.query(
                    IndexName=self.index_name,
                    KeyConditionExpression=Key(self.index_key).eq(geohash4),
                    Limit=50,
                )
                zones = resp.get("Items", [])
                self.cache[geohash4] = zones
            except Exception as e:
                logger.error(
                    f"Error querying hazard zones (index={self.index_name} key={self.index_key}): {e}"
                )
                return None

        if not zones:
            logger.warning(f"No hazard zone candidates found for geohash4={geohash4}")
            return None

        best = self._pick_best_zone(zones, latitude, longitude)
        return self._to_enrichment(best) if best else None

    def enrich_telemetry(self, telemetry: Dict) -> Dict:
        geohash = telemetry.get("geohash")
        lat = telemetry.get("latitude")
        lon = telemetry.get("longitude")

        if geohash and lat is not None and lon is not None:
            zone_data = self.get_hazard_zone(geohash, float(lat), float(lon))
            if zone_data:
                telemetry["nsdi_enrichment"] = zone_data
                telemetry["enriched"] = True
            else:
                telemetry["enriched"] = False

        return telemetry


class TelemetryWriter:
    def __init__(self, table):
        self.table = table

    def convert_floats_to_decimal(self, obj):
        if isinstance(obj, float):
            return Decimal(str(obj))
        if isinstance(obj, dict):
            return {k: self.convert_floats_to_decimal(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.convert_floats_to_decimal(i) for i in obj]
        return obj

    def add_metadata(self, telemetry: Dict) -> Dict:
        telemetry["ingested_at"] = datetime.utcnow().isoformat()
        ttl = datetime.utcnow() + timedelta(days=30)
        telemetry["ttl"] = int(ttl.timestamp())
        return telemetry

    def write_batch(self, telemetry_batch: List[Dict]) -> Dict:
        stats = {
            "total": len(telemetry_batch),
            "succeeded": 0,
            "failed": 0,
            "errors": [],
        }
        batch = [self.convert_floats_to_decimal(t) for t in telemetry_batch]
        batch = [self.add_metadata(t) for t in batch]

        with self.table.batch_writer() as writer:
            for item in batch:
                try:
                    writer.put_item(Item=item)
                    stats["succeeded"] += 1
                except Exception as e:
                    stats["failed"] += 1
                    stats["errors"].append(
                        {"sensor_id": item.get("sensor_id"), "error": str(e)}
                    )
                    logger.error(f"Failed to write {item.get('sensor_id')}: {e}")

        return stats


class EventBridgePublisher:
    HIGH_RISK_THRESHOLDS = {
        "moisture_percent": 85,
        "pore_pressure_kpa": 10,
        "tilt_rate_mm_hr": 5,
        "safety_factor": 1.2,
    }

    @classmethod
    def is_high_risk(cls, telemetry: Dict) -> bool:
        if (
            telemetry.get("moisture_percent", 0)
            >= cls.HIGH_RISK_THRESHOLDS["moisture_percent"]
        ):
            return True
        if (
            telemetry.get("pore_pressure_kpa", 0)
            >= cls.HIGH_RISK_THRESHOLDS["pore_pressure_kpa"]
        ):
            return True
        if (
            telemetry.get("tilt_rate_mm_hr", 0)
            >= cls.HIGH_RISK_THRESHOLDS["tilt_rate_mm_hr"]
        ):
            return True
        if (
            0
            < telemetry.get("safety_factor", 10)
            < cls.HIGH_RISK_THRESHOLDS["safety_factor"]
        ):
            return True

        nsdi = telemetry.get("nsdi_enrichment", {})
        if (
            nsdi.get("hazard_level") in ["High", "Very High"]
            and telemetry.get("moisture_percent", 0) > 70
        ):
            return True

        return False

    @classmethod
    def publish_event(cls, telemetry: Dict) -> None:
        try:
            event = {
                "Source": "openlews.ingestor",
                "DetailType": "HighRiskTelemetry",
                "Detail": json.dumps(
                    {
                        "sensor_id": telemetry["sensor_id"],
                        "timestamp": telemetry["timestamp"],
                        "latitude": telemetry["latitude"],
                        "longitude": telemetry["longitude"],
                        "moisture_percent": telemetry.get("moisture_percent"),
                        "pore_pressure_kpa": telemetry.get("pore_pressure_kpa"),
                        "safety_factor": telemetry.get("safety_factor"),
                        "hazard_level": telemetry.get("nsdi_enrichment", {}).get(
                            "hazard_level"
                        ),
                        "alert_reason": "Critical thresholds exceeded",
                    }
                ),
                "EventBusName": EVENT_BUS,
            }

            response = eventbridge.put_events(Entries=[event])
            if response.get("FailedEntryCount", 0) > 0:
                logger.error(f"EventBridge publish failed: {response}")
            else:
                logger.info(f"Published high-risk event for {telemetry['sensor_id']}")

        except Exception as e:
            logger.error(f"Error publishing to EventBridge: {e}")


def lambda_handler(event, context):
    logger.info(f"Received event: {json.dumps(event)}")

    try:
        if isinstance(event.get("body"), str):
            body = json.loads(event["body"])
        else:
            body = event

        telemetry_batch = body.get("telemetry", [])
        if not telemetry_batch:
            return {
                "statusCode": 400,
                "body": json.dumps(
                    {
                        "error": "No telemetry data provided",
                        "expected_format": '{"telemetry": [...]}',
                    }
                ),
            }

        logger.info(f"Processing {len(telemetry_batch)} telemetry records")

        validator = TelemetryValidator()
        enricher = NSDIEnricher(hazard_zones_table) if ENABLE_NSDI_ENRICHMENT else None
        writer = TelemetryWriter(telemetry_table)

        validated = []
        validation_errors = []
        high_risk_count = 0

        for idx, telemetry in enumerate(telemetry_batch):
            is_valid, error_msg = validator.validate(telemetry)
            if not is_valid:
                validation_errors.append(
                    {
                        "index": idx,
                        "sensor_id": telemetry.get("sensor_id", "unknown"),
                        "error": error_msg,
                    }
                )
                logger.warning(f"Validation failed for record {idx}: {error_msg}")
                continue

            if enricher:
                telemetry = enricher.enrich_telemetry(telemetry)

            if ENABLE_EVENTBRIDGE and EventBridgePublisher.is_high_risk(telemetry):
                EventBridgePublisher.publish_event(telemetry)
                high_risk_count += 1

            validated.append(telemetry)

        write_stats = {"succeeded": 0, "failed": 0}
        if validated:
            write_stats = writer.write_batch(validated)

        response_body = {
            "message": "Telemetry processed",
            "statistics": {
                "total_received": len(telemetry_batch),
                "validated": len(validated),
                "validation_errors": len(validation_errors),
                "written_to_dynamodb": write_stats.get("succeeded", 0),
                "write_failures": write_stats.get("failed", 0),
                "high_risk_events": high_risk_count,
            },
        }

        if validation_errors:
            response_body["validation_errors"] = validation_errors

        if write_stats.get("errors"):
            response_body["write_errors"] = write_stats["errors"]

        logger.info(f"Processing complete: {response_body['statistics']}")

        return {
            "statusCode": 200,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps(response_body),
        }

    except Exception as e:
        logger.error(f"Unhandled error: {e}", exc_info=True)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": "Internal server error", "message": str(e)}),
        }
