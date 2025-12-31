"""
RAG Query Lambda Handler
Connects sensor locations to hazard zones using DynamoDB GeoHashIndex

- Uses pygeohash for encoding
- Uses precision=4 by default (matches GeoHashIndex partition key like "tc1x")
- Uses an internal neighbour implementation
"""

from __future__ import annotations

import json
import math
import os
from decimal import Decimal
from typing import Any, Dict, List, Optional

import boto3
from boto3.dynamodb.conditions import Key

try:
    import pygeohash as pgh
except ImportError as e:
    raise RuntimeError(
        "pygeohash is required for this Lambda. Add it to requirements.txt and rebuild the deployment package."
    ) from e

try:
    from pinecone import Pinecone

    PINECONE_AVAILABLE = True
except ImportError:
    PINECONE_AVAILABLE = False


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
    t = "even" if (len(geohash) % 2 == 0) else "odd"

    if last in _BORDERS[direction][t] and parent:
        parent = _adjacent(parent, direction)

    idx = _NEIGHBORS[direction][t].find(last)
    if idx < 0:
        return ""

    return parent + _BASE32[idx]


def geohash_neighbors_8(cell: str) -> List[str]:
    cell = (cell or "").lower()
    if not cell:
        return []

    top = _adjacent(cell, "top")
    bottom = _adjacent(cell, "bottom")
    right = _adjacent(cell, "right")
    left = _adjacent(cell, "left")

    candidates = [
        cell,
        top,
        bottom,
        right,
        left,
        _adjacent(top, "right") if top else "",
        _adjacent(top, "left") if top else "",
        _adjacent(bottom, "right") if bottom else "",
        _adjacent(bottom, "left") if bottom else "",
    ]

    seen = set()
    out: List[str] = []
    for c in candidates:
        if c and len(c) == len(cell) and c not in seen:
            seen.add(c)
            out.append(c)
    return out


# Env
AWS_REGION = os.environ.get("AWS_REGION", "")
DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE_NAME", "")

GEOHASH_INDEX_NAME = os.environ.get("GEOHASH_INDEX_NAME", "GeoHashIndex")
GEOHASH_PRECISION = int(os.environ.get("GEOHASH_PRECISION", "4"))

PINECONE_API_KEY = os.environ.get("PINECONE_API_KEY")
PINECONE_INDEX_NAME = os.environ.get("PINECONE_INDEX_NAME", "")
PINECONE_NAMESPACE = os.environ.get("PINECONE_NAMESPACE", "")

dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
table = dynamodb.Table(DYNAMODB_TABLE)

pinecone_index = None
if PINECONE_AVAILABLE and PINECONE_API_KEY:
    try:
        pc = Pinecone(api_key=PINECONE_API_KEY)
        pinecone_index = pc.Index(PINECONE_INDEX_NAME)
    except Exception as e:
        print(f"⚠️ Failed to initialise Pinecone: {e}")
        pinecone_index = None


class GeoCalculator:
    EARTH_RADIUS_KM = 6371.0

    @staticmethod
    def haversine_distance_m(
        lat1: float, lon1: float, lat2: float, lon2: float
    ) -> float:
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)

        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return (GeoCalculator.EARTH_RADIUS_KM * c) * 1000.0

    @staticmethod
    def calculate_geohash(lat: float, lon: float, precision: int) -> str:
        return pgh.encode(lat, lon, precision=precision)

    @staticmethod
    def get_geohash_neighbors(geohash: str) -> List[str]:
        return geohash_neighbors_8(geohash)


class RAGQueryHandler:
    @staticmethod
    def query_nearest_zone(
        latitude: float, longitude: float, max_distance_km: float = 5.0
    ) -> Dict[str, Any]:
        geohash = GeoCalculator.calculate_geohash(
            latitude, longitude, precision=GEOHASH_PRECISION
        )
        cells = GeoCalculator.get_geohash_neighbors(geohash)

        print(
            f"Geohash={geohash} precision={GEOHASH_PRECISION} cells={len(cells)} index={GEOHASH_INDEX_NAME}"
        )

        nearest_zone = None
        min_distance = float("inf")

        for gh in cells:
            try:
                resp = table.query(
                    IndexName=GEOHASH_INDEX_NAME,
                    KeyConditionExpression=Key("geohash").eq(gh),
                )

                for item in resp.get("Items", []):
                    zone_lat = float(item["centroid_lat"])
                    zone_lon = float(item["centroid_lon"])
                    dist_m = GeoCalculator.haversine_distance_m(
                        latitude, longitude, zone_lat, zone_lon
                    )

                    if dist_m <= (max_distance_km * 1000.0) and dist_m < min_distance:
                        min_distance = dist_m
                        hazard_level = item.get("hazard_level") or item.get(
                            "level", "Unknown"
                        )

                        nearest_zone = {
                            "zone_id": item.get("zone_id", "Unknown"),
                            "hazard_level": hazard_level,
                            "level": hazard_level,
                            "distance_meters": round(dist_m, 2),
                            "distance_m": round(dist_m, 2),
                            "centroid": {"lat": zone_lat, "lon": zone_lon},
                            "geohash": item.get("geohash", gh),
                            "district": item.get("district", "Unknown"),
                            "ds_division": item.get("ds_division", "Unknown"),
                            "gn_division": item.get("gn_division", "Unknown"),
                            "soil_type": item.get("soil_type", "Unknown"),
                            "land_use": item.get("land_use", "Unknown"),
                            "landslide_type": item.get("landslide_type", "Unknown"),
                            "area_sqm": (
                                float(item.get("metadata", {}).get("shape_area", 0))
                                if item.get("metadata")
                                else 0
                            ),
                            "metadata": RAGQueryHandler._serialize_metadata(
                                item.get("metadata", {})
                            ),
                        }

                        if item.get("slope_angle") is not None:
                            nearest_zone["slope_angle"] = float(item["slope_angle"])

            except Exception as e:
                print(f"Error querying geohash {gh}: {e}")

        if nearest_zone:
            return {
                "success": True,
                "nearest_zone": nearest_zone,
                "query_location": {"lat": latitude, "lon": longitude},
                "geohash_precision": GEOHASH_PRECISION,
            }

        return {
            "success": False,
            "message": f"No hazard zones found within {max_distance_km}km",
            "query_location": {"lat": latitude, "lon": longitude},
            "geohash_precision": GEOHASH_PRECISION,
            "hint": "Ensure your hazard-zones table stores 4-char geohash values in the GeoHashIndex partition key.",
        }

    @staticmethod
    def query_zones_in_radius(
        latitude: float, longitude: float, radius_km: float = 1.0
    ) -> Dict[str, Any]:
        geohash = GeoCalculator.calculate_geohash(
            latitude, longitude, precision=GEOHASH_PRECISION
        )
        cells = GeoCalculator.get_geohash_neighbors(geohash)

        zones: List[Dict[str, Any]] = []

        for gh in cells:
            try:
                resp = table.query(
                    IndexName=GEOHASH_INDEX_NAME,
                    KeyConditionExpression=Key("geohash").eq(gh),
                )

                for item in resp.get("Items", []):
                    zone_lat = float(item["centroid_lat"])
                    zone_lon = float(item["centroid_lon"])
                    dist_m = GeoCalculator.haversine_distance_m(
                        latitude, longitude, zone_lat, zone_lon
                    )

                    if dist_m <= (radius_km * 1000.0):
                        hazard_level = item.get("hazard_level") or item.get(
                            "level", "Unknown"
                        )
                        zones.append(
                            {
                                "zone_id": item.get("zone_id", "Unknown"),
                                "hazard_level": hazard_level,
                                "level": hazard_level,
                                "distance_meters": round(dist_m, 2),
                                "distance_m": round(dist_m, 2),
                                "centroid": {"lat": zone_lat, "lon": zone_lon},
                                "geohash": item.get("geohash", gh),
                                "district": item.get("district", "Unknown"),
                                "soil_type": item.get("soil_type", "Unknown"),
                                "area_sqm": (
                                    float(item.get("metadata", {}).get("shape_area", 0))
                                    if item.get("metadata")
                                    else 0
                                ),
                            }
                        )

            except Exception as e:
                print(f"Error querying geohash {gh}: {e}")

        zones.sort(key=lambda x: x["distance_meters"])

        level_counts: Dict[str, int] = {}
        for z in zones:
            lvl = z["hazard_level"]
            level_counts[lvl] = level_counts.get(lvl, 0) + 1

        return {
            "success": True,
            "zones": zones,
            "count": len(zones),
            "query_location": {"lat": latitude, "lon": longitude},
            "radius_km": radius_km,
            "risk_summary": level_counts,
            "risk_context": RAGQueryHandler._generate_risk_context(zones, level_counts),
            "geohash_precision": GEOHASH_PRECISION,
        }

    @staticmethod
    def query_semantic(
        query_text: str, top_k: int = 5, filters: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        if not pinecone_index:
            return {
                "success": False,
                "message": "Semantic search requires Pinecone (not configured)",
                "suggestion": "Use nearest or radius queries instead",
            }

        return {
            "success": False,
            "message": "Semantic search not implemented in this Lambda yet",
            "suggestion": "Use nearest or radius queries instead",
        }

    @staticmethod
    def _serialize_metadata(metadata: Dict[str, Any]) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for k, v in (metadata or {}).items():
            if isinstance(v, Decimal):
                out[k] = float(v)
            elif isinstance(v, dict):
                out[k] = RAGQueryHandler._serialize_metadata(v)
            else:
                out[k] = v
        return out

    @staticmethod
    def _generate_risk_context(
        zones: List[Dict[str, Any]], level_counts: Dict[str, int]
    ) -> str:
        if not zones:
            return "No hazard zones in vicinity"
        nearest = zones[0]
        parts = [
            f"Nearest zone is {nearest['hazard_level']} hazard level",
            f"({nearest['distance_meters']:.0f}m away)",
        ]
        high_count = level_counts.get("High", 0) + level_counts.get("Very High", 0)
        if high_count > 0:
            parts.append(f"{high_count} HIGH risk zone(s) detected")
        return ". ".join(parts)


def _parse_event(event: Any) -> Dict[str, Any]:
    """Supports direct invoke payloads and API Gateway/Lambda URL style payloads."""
    if isinstance(event, dict) and isinstance(event.get("body"), str):
        try:
            return json.loads(event["body"])
        except Exception:
            return event
    if isinstance(event, dict):
        return event
    return {}


def lambda_handler(event: Any, context: Any) -> Dict[str, Any]:
    try:
        ev = _parse_event(event)
        action = ev.get("action", "nearest")

        if action == "nearest":
            latitude = float(ev["latitude"])
            longitude = float(ev["longitude"])
            max_distance_km = float(ev.get("max_distance_km", 5.0))
            result = RAGQueryHandler.query_nearest_zone(
                latitude, longitude, max_distance_km
            )

        elif action == "radius":
            latitude = float(ev["latitude"])
            longitude = float(ev["longitude"])
            radius_km = float(ev.get("radius_km", 1.0))
            result = RAGQueryHandler.query_zones_in_radius(
                latitude, longitude, radius_km
            )

        elif action == "semantic":
            query_text = str(ev["query_text"])
            top_k = int(ev.get("top_k", 5))
            filters = ev.get("filters")
            result = RAGQueryHandler.query_semantic(query_text, top_k, filters)

        else:
            result = {"success": False, "error": f"Unknown action: {action}"}

        return {
            "statusCode": 200 if result.get("success") else 400,
            "headers": {
                "Content-Type": "application/json",
                "Access-Control-Allow-Origin": "*",
            },
            "body": json.dumps(result, default=str),
        }

    except KeyError as e:
        return {
            "statusCode": 400,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(
                {"success": False, "error": f"Missing required parameter: {str(e)}"}
            ),
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"success": False, "error": str(e)}),
        }
