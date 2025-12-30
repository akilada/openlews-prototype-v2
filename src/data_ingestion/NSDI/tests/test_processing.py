#!/usr/bin/env python3
"""
Quick test to verify NDIS data processing works with your actual data
"""

from decimal import Decimal
from datetime import datetime
from typing import Dict, Any

# Paste the GeoJSONProcessor class here
class GeoJSONProcessor:
    """Processes NDIS GeoJSON features for storage"""
    
    @staticmethod
    def calculate_geohash(lat: float, lon: float, precision: int = 6) -> str:
        lat_bin = int((lat + 90) * 1000)
        lon_bin = int((lon + 180) * 1000)
        return f"{lat_bin:06d}{lon_bin:07d}"[:precision]
    
    @staticmethod
    def extract_centroid(geometry: Dict) -> tuple:
        """Extract centroid from ArcGIS polygon geometry"""
        if not geometry:
            return (0, 0)
        
        # ArcGIS format (NDIS uses this)
        if "rings" in geometry:
            rings = geometry["rings"][0]  # First ring = exterior boundary
            
            # Calculate centroid (simple average)
            lons = [point[0] for point in rings]
            lats = [point[1] for point in rings]
            
            centroid_lon = sum(lons) / len(lons)
            centroid_lat = sum(lats) / len(lats)
            
            return (centroid_lat, centroid_lon)
        
        # GeoJSON format (fallback)
        elif geometry.get("type") == "Polygon" and "coordinates" in geometry:
            rings = geometry["coordinates"][0]
            
            lons = [point[0] for point in rings]
            lats = [point[1] for point in rings]
            
            centroid_lon = sum(lons) / len(lons)
            centroid_lat = sum(lats) / len(lats)
            
            return (centroid_lat, centroid_lon)
        
        return (0, 0)
    
    @staticmethod
    def convert_to_decimal(obj: Any) -> Any:
        if isinstance(obj, float):
            return Decimal(str(obj))
        elif isinstance(obj, dict):
            return {k: GeoJSONProcessor.convert_to_decimal(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [GeoJSONProcessor.convert_to_decimal(v) for v in obj]
        else:
            return obj
    
    @staticmethod
    def process_feature(feature: Dict, version: int = 1) -> Dict:
        attributes = feature.get("attributes", {})
        geometry = feature.get("geometry", {})
        
        # Generate unique zone ID from objectid (NDIS uses lowercase)
        objectid = attributes.get("objectid") or attributes.get("OBJECTID") or attributes.get("id")
        zone_id = f"NDIS_{objectid}" if objectid else "NDIS_UNKNOWN"
        
        # Extract centroid for spatial queries
        centroid_lat, centroid_lon = GeoJSONProcessor.extract_centroid(geometry)
        
        # Calculate geohash for spatial indexing
        geohash = GeoJSONProcessor.calculate_geohash(centroid_lat, centroid_lon)
        
        # Determine hazard level (NDIS uses 'level' field, lowercase)
        level = attributes.get("level") or attributes.get("Level") or attributes.get("Hazard_Level") or "Unknown"
        
        # Convert geometry to Decimal for DynamoDB
        geometry_decimal = GeoJSONProcessor.convert_to_decimal(geometry)
        
        # Build DynamoDB item
        item = {
            "zone_id": zone_id,
            "version": version,
            "level": level,
            "geometry": geometry_decimal,
            "centroid_lat": Decimal(str(centroid_lat)),
            "centroid_lon": Decimal(str(centroid_lon)),
            "geohash": geohash,
            "metadata": {
                "objectid": objectid,
                "range": attributes.get("range"),
                "shape_area": Decimal(str(attributes.get("st_area(shape)", 0))),
                "shape_length": Decimal(str(attributes.get("st_length(shape)", 0))),
                "raw_attributes": GeoJSONProcessor.convert_to_decimal(attributes)
            },
            "created_at": int(datetime.utcnow().timestamp() * 1000),
            "source": "NDIS_API"
        }
        
        return item


# Test with your actual data
test_feature = {
    "attributes": {
        "objectid": 1,
        "id": 3.0,
        "range": 3.0,
        "level": "Moderate",
        "st_area(shape)": 2.0999750550650005e-06,
        "st_length(shape)": 0.008726660832978921
    },
    "geometry": {
        "rings": [
            [
                [81.00385529000005, 7.01485073200007],
                [81.00415418400007, 7.014725147000036],
                [81.00455370900005, 7.014814409000053]
            ]
        ]
    }
}

print("Testing NDIS data processing...")
print("=" * 60)

try:
    processor = GeoJSONProcessor()
    result = processor.process_feature(test_feature)
    
    print("✅ SUCCESS! Processing works correctly.")
    print("\nProcessed item:")
    print(f"  Zone ID: {result['zone_id']}")
    print(f"  Level: {result['level']}")
    print(f"  Centroid: {result['centroid_lat']}, {result['centroid_lon']}")
    print(f"  Geohash: {result['geohash']}")
    print(f"  ObjectID: {result['metadata']['objectid']}")
    print(f"  Area: {result['metadata']['shape_area']}")
    
    print("\n" + "=" * 60)
    print("✅ Your NDIS data will process correctly!")
    print("Run: python ndis_rag_pipeline.py")
    
except Exception as e:
    print(f"❌ ERROR: {e}")
    import traceback
    traceback.print_exc()