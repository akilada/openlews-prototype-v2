"""
Shared GeoJSON Processing Module for NSDI Data

Used by:
- nsdi_rag_pipeline.py (live downloads)
- process_backup.py (backup file processing)

Goal:
- Consistent geohash generation
- Safe DynamoDB item structure (avoid 400KB)
- Embedding text that supports demo-quality semantic search
"""

from decimal import Decimal
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

try:
    import pygeohash as pgh
    GEOHASH_AVAILABLE = True
except ImportError:
    GEOHASH_AVAILABLE = False
    print("⚠️  pygeohash not installed. Using simple coordinate hash.")
    print("   Install with: pip install pygeohash")


class GeoHashCalculator:
    """Handles geohash calculations with proper library support."""

    @staticmethod
    def encode(lat: float, lon: float, precision: int = 6) -> str:
        """Calculate geohash for spatial indexing."""
        if GEOHASH_AVAILABLE:
            try:
                return pgh.encode(lat, lon, precision=precision)
            except Exception as e:
                print(f"  ⚠️  Geohash encoding failed: {e}, using fallback")
        return GeoHashCalculator._simple_hash(lat, lon, precision)

    @staticmethod
    def _simple_hash(lat: float, lon: float, precision: int = 6) -> str:
        """Simple coordinate-based hash fallback (no neighbor queries)."""
        lat_bin = int((lat + 90) * 1000)
        lon_bin = int((lon + 180) * 1000)
        return f"{lat_bin:06d}{lon_bin:06d}"[:precision]

    @staticmethod
    def neighbors(geohash: str) -> List[str]:
        """Get neighboring geohashes for expanded spatial search."""
        if GEOHASH_AVAILABLE:
            try:
                neighbor_dict = pgh.neighbors(geohash)
                return [geohash] + list(neighbor_dict.values())
            except Exception as e:
                print(f"  ⚠️  Neighbor calculation failed: {e}, using fallback")
        return GeoHashCalculator._simple_neighbors(geohash)

    @staticmethod
    def _simple_neighbors(geohash: str) -> List[str]:
        """Simple neighbor approximation for numeric fallback hashes."""
        neighbors = [geohash]
        if len(geohash) < 2:
            return neighbors

        try:
            base = geohash[:-2]
            last_two = int(geohash[-2:])
            for offset in [-11, -10, -9, -1, 0, 1, 9, 10, 11]:
                new_val = last_two + offset
                if 0 <= new_val <= 99:
                    neighbors.append(f"{base}{new_val:02d}")
        except ValueError:
            pass

        return list(set(neighbors))

    @staticmethod
    def is_real_geohash() -> bool:
        return GEOHASH_AVAILABLE


class GeoJSONProcessor:
    """
    Processes NSDI GeoJSON features for DynamoDB/Pinecone storage.
    """

    NSDI_BASE_URL = "https://gisapps.nsdi.gov.lk/server/rest/services/SLNSDI/Geo_Scientific_Information/MapServer/8"

    @staticmethod
    def extract_centroid(geometry: Dict) -> Tuple[float, float]:
        """Extract centroid from polygon geometry (ArcGIS rings or GeoJSON polygon)."""
        if not geometry:
            return (0.0, 0.0)

        if "rings" in geometry:
            rings = geometry["rings"][0] if geometry["rings"] else []
            if not rings:
                return (0.0, 0.0)
            lons = [pt[0] for pt in rings]
            lats = [pt[1] for pt in rings]
            return (sum(lats) / len(lats), sum(lons) / len(lons))

        if geometry.get("type") == "Polygon" and "coordinates" in geometry:
            rings = geometry["coordinates"][0] if geometry["coordinates"] else []
            if not rings:
                return (0.0, 0.0)
            lons = [pt[0] for pt in rings]
            lats = [pt[1] for pt in rings]
            return (sum(lats) / len(lats), sum(lons) / len(lons))

        return (0.0, 0.0)

    @staticmethod
    def calculate_bounding_box(geometry: Dict) -> Optional[Dict]:
        """Calculate bounding box (min/max lat/lon) to save space."""
        if not geometry:
            return None

        rings = None
        if "rings" in geometry:
            rings = geometry["rings"][0] if geometry["rings"] else None
        elif geometry.get("type") == "Polygon" and "coordinates" in geometry:
            rings = geometry["coordinates"][0] if geometry["coordinates"] else None

        if not rings:
            return None

        lons = [pt[0] for pt in rings]
        lats = [pt[1] for pt in rings]

        return {
            "min_lat": Decimal(str(min(lats))),
            "max_lat": Decimal(str(max(lats))),
            "min_lon": Decimal(str(min(lons))),
            "max_lon": Decimal(str(max(lons))),
        }

    @staticmethod
    def count_geometry_points(geometry: Dict) -> int:
        """Count points for size estimation/debug."""
        if not geometry:
            return 0
        if "rings" in geometry:
            return sum(len(ring) for ring in geometry.get("rings", []))
        if "coordinates" in geometry:
            coords = geometry.get("coordinates", [])
            if coords and isinstance(coords[0], list):
                return sum(len(ring) for ring in coords)
        return 0

    @staticmethod
    def convert_to_decimal(obj: Any) -> Any:
        """Recursively convert floats to Decimal (DynamoDB compatibility)."""
        if obj is None:
            return None
        if isinstance(obj, bool):
            return obj
        if isinstance(obj, int):
            return obj
        if isinstance(obj, float):
            return Decimal(str(obj))
        if isinstance(obj, Decimal):
            return obj
        if isinstance(obj, str):
            return obj
        if isinstance(obj, dict):
            return {k: GeoJSONProcessor.convert_to_decimal(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [GeoJSONProcessor.convert_to_decimal(v) for v in obj]
        return obj

    @staticmethod
    def extract_field(attributes: Dict, field_names: List[str], default: str = "Unknown") -> str:
        """Try multiple field names due to inconsistent NSDI attribute naming."""
        for field in field_names:
            if attributes.get(field) is not None and str(attributes.get(field)).strip() != "":
                return str(attributes[field]).strip()
        return default

    @staticmethod
    def extract_numeric_field(attributes: Dict, field_names: List[str]) -> Optional[Decimal]:
        """Try multiple numeric field names."""
        for field in field_names:
            val = attributes.get(field)
            if val is not None:
                try:
                    return Decimal(str(float(val)))
                except (ValueError, TypeError):
                    pass
        return None

    @staticmethod
    def normalize_hazard_level(raw: str) -> str:
        """
        Normalise hazard level to stable canonical values.
        Keeps this conservative (doesn't invent levels).
        """
        if not raw:
            return "Unknown"
        s = str(raw).strip()
        s = s.replace("_", " ").replace("-", " ")
        s = " ".join(s.split())
        s = s.title()
        if s in ("Veryhigh", "Very High"):
            return "Very High"
        return s

    @classmethod
    def process_feature(
        cls,
        feature: Dict,
        version: int = 1,
        include_geometry: bool = False,
        source_url: Optional[str] = None
    ) -> Dict:
        """Process a single NSDI feature for DynamoDB storage."""
        attributes = feature.get("attributes", {})
        geometry = feature.get("geometry", {})

        objectid = attributes.get("objectid") or attributes.get("OBJECTID") or attributes.get("id")
        zone_id = f"NSDI_{int(objectid)}" if objectid else "NSDI_UNKNOWN"

        centroid_lat, centroid_lon = cls.extract_centroid(geometry)
        geohash6 = GeoHashCalculator.encode(centroid_lat, centroid_lon, precision=6)
        geohash4 = geohash6[:4]        
        
        geohash = geohash4

        level_raw = cls.extract_field(
            attributes,
            ["level", "Level", "LEVEL", "hazard_level", "Hazard_Level", "HAZARD_LEVEL"],
            "Unknown"
        )
        level = cls.normalize_hazard_level(level_raw)

        district = cls.extract_field(attributes, ["district", "District", "DISTRICT", "dist", "Dist"])
        ds_division = cls.extract_field(attributes, ["ds_division", "DS_Division", "DS_DIVISION", "dsd", "DSD", "ds_div"])
        gn_division = cls.extract_field(attributes, ["gn_division", "GN_Division", "GN_DIVISION", "gnd", "GND", "gn_div"])

        soil_type = cls.extract_field(attributes, ["soil_type", "Soil_Type", "SOIL_TYPE", "soil", "Soil", "geology", "Geology"])
        landslide_type = cls.extract_field(attributes, ["landslide_type", "Landslide_Type", "LANDSLIDE_TYPE", "ls_type", "LS_Type", "type"])
        land_use = cls.extract_field(attributes, ["land_use", "Land_Use", "LAND_USE", "landuse", "LandUse"])

        slope_angle = cls.extract_numeric_field(attributes, ["slope_angle", "Slope_Angle", "SLOPE_ANGLE", "slope", "Slope", "gradient"])

        bbox = cls.calculate_bounding_box(geometry)

        item = {
            "zone_id": zone_id,
            "version": version,

            "level": level,
            "hazard_level": level,

            "centroid_lat": Decimal(str(centroid_lat)),
            "centroid_lon": Decimal(str(centroid_lon)),
            "geohash": geohash,
            "geohash4": geohash4,
            "geohash6": geohash6,

            "district": district,
            "ds_division": ds_division,
            "gn_division": gn_division,
            "soil_type": soil_type,
            "landslide_type": landslide_type,
            "land_use": land_use,

            "metadata": {
                "objectid": int(objectid) if objectid else None,
                "range": Decimal(str(attributes.get("range"))) if attributes.get("range") is not None else None,
                "shape_area": Decimal(str(attributes.get("st_area(shape)", 0))),
                "shape_length": Decimal(str(attributes.get("st_length(shape)", 0))),
                "geometry_points": cls.count_geometry_points(geometry),
            },
            "created_at": int(datetime.utcnow().timestamp() * 1000),
            "source": "NSDI_API",
            "source_url": source_url or cls.NSDI_BASE_URL,
        }

        if bbox:
            item["bounding_box"] = bbox
        if slope_angle is not None:
            item["slope_angle"] = slope_angle
        if include_geometry:
            item["geometry"] = cls.convert_to_decimal(geometry)

        return cls.convert_to_decimal(item)

    @staticmethod
    def generate_embedding_text(item: Dict) -> str:
        """
        Generate text used for embeddings.

        MVP improvement: "anchor" hazard severity strongly so semantic queries
        like "very high risk" and "dangerous" map correctly.
        """
        level = GeoJSONProcessor.normalize_hazard_level(
            item.get("hazard_level") or item.get("level") or "Unknown"
        )

        severity_anchors = [
            f"landslide hazard level: {level}",
            f"{level} landslide risk",
            f"risk severity {level}",
        ]

        parts = [
            f"NSDI landslide hazard zone {item.get('zone_id', 'Unknown')}.",
            *severity_anchors,
            f"geohash {item.get('geohash', 'unknown')}",
            f"location latitude {float(item.get('centroid_lat', 0.0)):.4f} longitude {float(item.get('centroid_lon', 0.0)):.4f}",
            f"district {item.get('district', 'Unknown')}",
            f"ds division {item.get('ds_division', 'Unknown')}",
            f"gn division {item.get('gn_division', 'Unknown')}",
            f"soil type {item.get('soil_type', 'Unknown')}",
            f"landslide type {item.get('landslide_type', 'Unknown')}",
            f"land use {item.get('land_use', 'Unknown')}",
        ]

        area = (item.get("metadata", {}) or {}).get("shape_area")
        if area is not None:
            parts.append(f"shape area {float(area)}")

        slope = item.get("slope_angle")
        if slope is not None:
            parts.append(f"slope angle degrees {float(slope)}")

        return " | ".join(parts)


def estimate_item_size(item: Dict) -> int:
    """Estimate size in bytes for DynamoDB 400KB limit checks."""
    import json
    return len(json.dumps(item, default=str).encode("utf-8"))
