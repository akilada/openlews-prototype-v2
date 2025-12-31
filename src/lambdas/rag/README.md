# RAG Query Engine Lambda

**Geospatial Hazard Zone Lookup with Geohash Indexing**

---

## Overview

The RAG Query Engine connects sensor locations to NSDI hazard zones using DynamoDB's GeoHashIndex. It provides fast geospatial queries to retrieve relevant geological context for landslide risk assessment.

This component enables **Strategy A: Contextual Verification** by looking up the hazard zone characteristics for any given sensor location, allowing the detection engine to validate sensor anomalies against geological reality.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        RAG Query Engine Lambda                          │
│                                                                         │
│  ┌──────────────┐    ┌──────────────────────────────────────────────┐   │
│  │ Query        │    │ Geohash Computation                          │   │
│  │ Parser       │ →  │ - pygeohash encoding (precision=4)           │   │
│  │              │    │ - 8-neighbor cell expansion                  │   │
│  └──────────────┘    └──────────────────────────────────────────────┘   │
│                                    ↓                                    │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                    DynamoDB GeoHashIndex Query                   │   │
│  │  - Query each neighbor cell                                      │   │
│  │  - Retrieve candidate hazard zones                               │   │
│  │  - Calculate Haversine distance                                  │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                    ↓                                    │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                    Result Processing                             │   │
│  │  - Filter by max distance                                        │   │
│  │  - Sort by proximity                                             │   │
│  │  - Generate risk context summary                                 │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                    Pinecone (Optional)                           │   │
│  │  - Semantic search capability                                    │   │
│  │  - Not yet implemented in current version                        │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Core Components

### 1. Geohash Neighbor Computation

The Lambda includes a custom implementation for computing geohash neighbors, avoiding external dependencies:

```python
_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"
_NEIGHBORS = {
    "right": {"even": "bc01fg45238967deuvhjyznpkmstqrwx",
              "odd":  "p0r21436x8zb9dcf5h7kjnmqesgutwvy"},
    "left":  {"even": "238967debc01fg45kmstqrwxuvhjyznp",
              "odd":  "14365h7k9dcfesgujnmqp0r2twvyx8zb"},
    "top":   {"even": "p0r21436x8zb9dcf5h7kjnmqesgutwvy",
              "odd":  "bc01fg45238967deuvhjyznpkmstqrwx"},
    "bottom":{"even": "14365h7k9dcfesgujnmqp0r2twvyx8zb",
              "odd":  "238967debc01fg45kmstqrwxuvhjyznp"},
}

def geohash_neighbors_8(cell: str) -> List[str]:
    """
    Returns the cell itself plus its 8 surrounding neighbors.
    Handles edge cases at geohash boundaries.
    """
    top = _adjacent(cell, "top")
    bottom = _adjacent(cell, "bottom")
    right = _adjacent(cell, "right")
    left = _adjacent(cell, "left")
    
    return [
        cell,
        top, bottom, right, left,
        _adjacent(top, "right"),
        _adjacent(top, "left"),
        _adjacent(bottom, "right"),
        _adjacent(bottom, "left"),
    ]
```

### 2. GeoCalculator Class

Provides geospatial utilities:

```python
class GeoCalculator:
    EARTH_RADIUS_KM = 6371.0

    @staticmethod
    def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance between two points in meters."""
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)

        a = (math.sin(dlat / 2) ** 2 +
             math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return (GeoCalculator.EARTH_RADIUS_KM * c) * 1000.0

    @staticmethod
    def calculate_geohash(lat: float, lon: float, precision: int) -> str:
        """Encode coordinates to geohash using pygeohash."""
        return pgh.encode(lat, lon, precision=precision)

    @staticmethod
    def get_geohash_neighbors(geohash: str) -> List[str]:
        """Get center cell plus 8 surrounding neighbors."""
        return geohash_neighbors_8(geohash)
```

### 3. RAGQueryHandler Class

Main query logic:

```python
class RAGQueryHandler:
    @staticmethod
    def query_nearest_zone(latitude: float, longitude: float, max_distance_km: float = 5.0) -> Dict[str, Any]:
        """Find the nearest hazard zone to given coordinates."""
        
    @staticmethod
    def query_zones_in_radius(latitude: float, longitude: float, radius_km: float = 1.0) -> Dict[str, Any]:
        """Find all hazard zones within a radius."""
        
    @staticmethod
    def query_semantic(query_text: str, top_k: int = 5, filters: Optional[Dict] = None) -> Dict[str, Any]:
        """Semantic search (not yet implemented)."""
```

---

## Query Types

### Action: `nearest`

Find the single nearest hazard zone to a location:

**Request:**
```json
{
  "action": "nearest",
  "latitude": 6.85,
  "longitude": 80.93,
  "max_distance_km": 5.0
}
```

**Response:**
```json
{
  "success": true,
  "nearest_zone": {
    "zone_id": "BADULLA-HZ-2341",
    "hazard_level": "High",
    "level": "High",
    "distance_meters": 234.56,
    "distance_m": 234.56,
    "centroid": {"lat": 6.851, "lon": 80.932},
    "geohash": "tc1x",
    "district": "Badulla",
    "ds_division": "Haldummulla",
    "gn_division": "Meeriyabedda",
    "soil_type": "Colluvium",
    "land_use": "Tea",
    "landslide_type": "Debris flow",
    "area_sqm": 125000,
    "slope_angle": 32.5,
    "metadata": {
      "shape_area": 125000
    }
  },
  "query_location": {"lat": 6.85, "lon": 80.93},
  "geohash_precision": 4
}
```

### Action: `radius`

Find all hazard zones within a specified radius:

**Request:**
```json
{
  "action": "radius",
  "latitude": 6.85,
  "longitude": 80.93,
  "radius_km": 1.0
}
```

**Response:**
```json
{
  "success": true,
  "zones": [
    {
      "zone_id": "BADULLA-HZ-2341",
      "hazard_level": "High",
      "level": "High",
      "distance_meters": 234.56,
      "distance_m": 234.56,
      "centroid": {"lat": 6.851, "lon": 80.932},
      "geohash": "tc1x",
      "district": "Badulla",
      "soil_type": "Colluvium",
      "area_sqm": 125000
    },
    {
      "zone_id": "BADULLA-HZ-2342",
      "hazard_level": "Medium",
      "level": "Medium",
      "distance_meters": 567.89,
      "distance_m": 567.89,
      "centroid": {"lat": 6.853, "lon": 80.928},
      "geohash": "tc1x",
      "district": "Badulla",
      "soil_type": "Residual",
      "area_sqm": 98000
    }
  ],
  "count": 2,
  "query_location": {"lat": 6.85, "lon": 80.93},
  "radius_km": 1.0,
  "risk_summary": {
    "High": 1,
    "Medium": 1
  },
  "risk_context": "Nearest zone is High hazard level (235m away). 1 HIGH risk zone(s) detected",
  "geohash_precision": 4
}
```

### Action: `semantic`

Semantic search using Pinecone (not yet implemented):

**Request:**
```json
{
  "action": "semantic",
  "query_text": "colluvium soil failure patterns",
  "top_k": 5,
  "filters": {"soil_type": "Colluvium"}
}
```

**Response:**
```json
{
  "success": false,
  "message": "Semantic search not implemented in this Lambda yet",
  "suggestion": "Use nearest or radius queries instead"
}
```

---

## DynamoDB Schema Requirements

The Lambda expects a DynamoDB table with the following structure:

### Table: NSDIHazardZones

| Attribute | Type | Description |
|-----------|------|-------------|
| zone_id | String | Primary key |
| geohash | String | 4-character geohash (GSI partition key) |
| centroid_lat | Number | Zone centroid latitude |
| centroid_lon | Number | Zone centroid longitude |
| hazard_level / level | String | Low, Medium, High, Very High |
| district | String | Administrative district |
| ds_division | String | Divisional Secretariat |
| gn_division | String | Grama Niladhari division |
| soil_type | String | Colluvium, Residual, etc. |
| land_use | String | Tea, Rubber, Forest, etc. |
| landslide_type | String | Debris flow, Rotational, etc. |
| slope_angle | Number | Slope in degrees (optional) |
| metadata | Map | Additional properties including shape_area |

### Required GSI: GeoHashIndex

| Key Type | Attribute |
|----------|-----------|
| Partition Key | geohash |

**Important:** The geohash values stored must match the precision configured (default: 4 characters like "tc1x").

---

## Configuration

### Environment Variables

```bash
# AWS
AWS_REGION=<region>>

# DynamoDB
DYNAMODB_TABLE_NAME=NSDIHazardZones
GEOHASH_INDEX_NAME=GeoHashIndex
GEOHASH_PRECISION=4

# Pinecone (optional, for future semantic search)
PINECONE_API_KEY=pinecone-api-key
PINECONE_INDEX_NAME=pinecone-index
PINECONE_NAMESPACE=pinecone-namespace
```

### Geohash Precision

| Precision | Cell Size | Use Case |
|-----------|-----------|----------|
| 4 | ~39km × 19km | Default - good for regional queries |
| 5 | ~5km × 5km | More precise local queries |
| 6 | ~1.2km × 0.6km | High precision |

The Lambda uses precision=4 by default to match the GeoHashIndex partition key format.

---

## Algorithm Details

### Nearest Zone Query Flow

```
1. Encode (lat, lon) → geohash (precision=4)
   Example: (6.85, 80.93) → "tc1x"

2. Expand to 9 cells (center + 8 neighbors)
   ["tc1x", "tc1w", "tc1y", "tc1r", "tc1z", ...]

3. For each cell:
   - Query DynamoDB GeoHashIndex where geohash = cell
   - For each returned zone:
     - Calculate Haversine distance to query point
     - If distance < max_distance_km AND distance < current_minimum:
       - Update nearest_zone

4. Return nearest_zone with full metadata
```

### Risk Context Generation

```python
def _generate_risk_context(zones: List[Dict], level_counts: Dict[str, int]) -> str:
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
```

---

## Event Parsing

The Lambda supports both direct invocation and API Gateway/Lambda URL payloads:

```python
def _parse_event(event: Any) -> Dict[str, Any]:
    """Supports direct invoke and API Gateway style payloads."""
    # API Gateway with JSON body
    if isinstance(event, dict) and isinstance(event.get("body"), str):
        try:
            return json.loads(event["body"])
        except Exception:
            return event
    # Direct invocation
    if isinstance(event, dict):
        return event
    return {}
```

---

## Error Handling

| Error | HTTP Status | Response |
|-------|-------------|----------|
| Missing required parameter | 400 | `{"success": false, "error": "Missing required parameter: latitude"}` |
| No zones found | 200 | `{"success": false, "message": "No hazard zones found within 5km", "hint": "..."}` |
| DynamoDB query error | 500 | `{"success": false, "error": "..."}` |
| Unknown action | 400 | `{"success": false, "error": "Unknown action: xyz"}` |

### Troubleshooting Hint

When no zones are found, the response includes a hint:

```json
{
  "success": false,
  "message": "No hazard zones found within 5km",
  "hint": "Ensure your hazard-zones table stores 4-char geohash values in the GeoHashIndex partition key."
}
```

---

## Decimal Serialization

The Lambda handles DynamoDB's Decimal types for JSON serialization:

```python
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
```

---

## Dependencies

```
boto3>=1.28.0
pygeohash>=1.2.0
pinecone>=7.3.0
```

---

## Testing

### Unit Tests

```bash
pytest ./tests/test_rag_query.py -v
```

### Manual Testing

```python
# Test nearest zone query
import json
from rag_query_lambda import lambda_handler

event = {
    "action": "nearest",
    "latitude": 6.85,
    "longitude": 80.93,
    "max_distance_km": 5.0
}

response = lambda_handler(event, None)
result = json.loads(response["body"])
print(f"Nearest zone: {result.get('nearest_zone', {}).get('zone_id')}")
```

### Verify Geohash Index

```bash
# Check that zones are indexed with correct geohash precision
aws dynamodb query \
  --table-name NSDIHazardZones \
  --index-name GeoHashIndex \
  --key-condition-expression "geohash = :gh" \
  --expression-attribute-values '{":gh": {"S": "tc1x"}}' \
  --max-items 5
```

---

## Future Enhancements

1. **Semantic Search**: Complete Pinecone integration for similarity-based queries
2. **LLM Synthesis**: Add Claude integration for natural language risk explanations
3. **Point-in-Polygon**: Precise polygon containment checks (currently uses centroid distance)
4. **Caching**: Add zone caching for frequently queried locations

---

## Related Components

- [Detection Engine](../detector/README.md) - Primary consumer of hazard zone data
- [NSDI Data Loader](../../data_ingestion/NSDI/README.md) - Populates hazard zone data
- [Infrastructure](../../infrastructure/README.md) - DynamoDB table and GSI setup