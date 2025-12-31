"""
Location Resolver (Amazon Location Service)

Reverse-geocodes a latitude/longitude using an Amazon Location Place Index
and returns a consistent payload to store in DynamoDB and pass to Bedrock.

Fallback:
- If PLACE_INDEX_NAME is not set (or lookup fails), returns coordinates-only label + Google Maps URL.

"""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import boto3
from aws_lambda_powertools import Logger

logger = Logger(child=True)


def _fmt_coord_label(lat: float, lon: float) -> str:
    return f"{lat:.5f}, {lon:.5f}"


def _google_maps_search_url(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps/search/?api=1&query={lat:.6f},{lon:.6f}"


def _google_maps_dir_url(lat: float, lon: float) -> str:
    return f"https://www.google.com/maps/dir/?api=1&destination={lat:.6f},{lon:.6f}"


def _safe_get(d: Dict, *keys: str) -> Optional[Any]:
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return None
        cur = cur[k]
    return cur


class LocationResolver:
    def __init__(self) -> None:
        self.place_index_name = os.environ.get("PLACE_INDEX_NAME", "").strip()
        self.region = os.environ.get("LOCATION_REGION") or os.environ.get(
            "AWS_REGION", ""
        )
        self.language = os.environ.get("LOCATION_LANGUAGE", "en")
        self.max_results = int(os.environ.get("LOCATION_MAX_RESULTS", "1"))
        self.label_format = os.environ.get("LOCATION_LABEL_FORMAT", "short").lower()

        self._client = None
        if self.place_index_name:
            self._client = boto3.client("location", region_name=self.region)
            logger.info(
                "LocationResolver initialised",
                extra={"place_index": self.place_index_name, "region": self.region},
            )
        else:
            logger.warning(
                "LocationResolver: PLACE_INDEX_NAME not set - falling back to coordinates only",
                extra={"region": self.region},
            )

    def resolve(self, latitude: float, longitude: float) -> Dict[str, Any]:
        """
        Returns:
        {
          "location_label": "...",
          "google_maps_url": "...",
          "google_maps_directions_url": "...",
          "resolved_by": "amazon_location|coordinates_only|amazon_location_error",
          "address": {...},
          "place": {...},
          "latitude": <float>,
          "longitude": <float>,
        }
        """
        base = {
            "latitude": float(latitude),
            "longitude": float(longitude),
            "location_label": _fmt_coord_label(latitude, longitude),
            "google_maps_url": _google_maps_search_url(latitude, longitude),
            "google_maps_directions_url": _google_maps_dir_url(latitude, longitude),
            "resolved_by": "coordinates_only",
            "address": {},
            "place": {},
        }

        if not self._client:
            return base

        try:
            # Amazon Location expects Position=[lon, lat]
            resp = self._client.search_place_index_for_position(
                IndexName=self.place_index_name,
                Position=[float(longitude), float(latitude)],
                MaxResults=self.max_results,
                Language=self.language,
            )

            results = resp.get("Results") or []
            if not results:
                logger.info(
                    "Amazon Location: no reverse-geocode results",
                    extra={"lat": latitude, "lon": longitude},
                )
                return base

            top = results[0] or {}
            place = top.get("Place") or {}

            # Common fields across providers
            label = place.get("Label")
            municipality = place.get("Municipality")
            subregion = place.get("SubRegion")
            region = place.get("Region")
            country = place.get("Country")
            postal = place.get("PostalCode")
            neighbourhood = place.get("Neighborhood")
            street = place.get("Street")
            address_number = place.get("AddressNumber")

            # Build a "short" label for alerts
            parts_short = [
                p
                for p in [neighbourhood, municipality, subregion, region, country]
                if p
            ]
            short_label = ", ".join(parts_short) if parts_short else None

            # Build a structured address dict for storage/search
            address = {
                "label": label,
                "address_number": address_number,
                "street": street,
                "neighborhood": neighbourhood,
                "municipality": municipality,
                "subregion": subregion,
                "region": region,
                "country": country,
                "postal_code": postal,
            }
            # Drop empties
            address = {k: v for k, v in address.items() if v}

            geom_point = _safe_get(place, "Geometry", "Point")
            provider_lon = provider_lat = None
            if isinstance(geom_point, (list, tuple)) and len(geom_point) == 2:
                provider_lon, provider_lat = float(geom_point[0]), float(geom_point[1])

            place_id = place.get("PlaceId")

            resolved_label = (
                label if self.label_format == "full" else (short_label or label)
            )
            if not resolved_label:
                resolved_label = _fmt_coord_label(latitude, longitude)

            out = {
                **base,
                "location_label": resolved_label,
                "resolved_by": "amazon_location",
                "address": address,
                "place": {
                    "place_id": place_id,
                    "provider_geometry": (
                        {"lat": provider_lat, "lon": provider_lon}
                        if provider_lat and provider_lon
                        else {}
                    ),
                    "raw": {},
                },
            }

            logger.info(
                "Amazon Location resolved",
                extra={
                    "lat": latitude,
                    "lon": longitude,
                    "label": resolved_label,
                    "region": self.region,
                    "place_index": self.place_index_name,
                },
            )
            return out

        except Exception as e:
            logger.exception(
                "Amazon Location reverse-geocode failed", extra={"error": str(e)}
            )
            base["resolved_by"] = "amazon_location_error"
            return base
