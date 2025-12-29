# Telemetry Ingestor Lambda

**Sensor Telemetry Ingestion with Validation, NDIS Enrichment, and High-Risk Event Publishing**

---

## Overview

The Telemetry Ingestor Lambda receives sensor telemetry data, validates it, enriches it with NDIS hazard zone information, writes it to DynamoDB, and publishes high-risk events to EventBridge for downstream processing.

---

## Architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│                      Telemetry Ingestor Lambda                         │
│                                                                        │
│  ┌──────────────┐    ┌──────────────────────────────────────────────┐  │
│  │ Event        │    │ TelemetryValidator                           │  │
│  │ Parser       │ →  │ - Required fields check                      │  │
│  │              │    │ - Range validation                           │  │
│  │              │    │ - Timestamp normalization                    │  │
│  └──────────────┘    └──────────────────────────────────────────────┘  │
│                                    ↓                                   │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                    NDISEnricher                                  │  │
│  │  - Query hazard zones by geohash4                                │  │
│  │  - Bounding box containment check                                │  │
│  │  - Pick highest-risk zone                                        │  │
│  │  - Add hazard_level, district, soil_type, etc.                   │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                                    ↓                                   │
│  ┌─────────────────────────┐    ┌───────────────────────────────────┐  │
│  │   TelemetryWriter       │    │   EventBridgePublisher            │  │
│  │   - Float → Decimal     │    │   - High-risk threshold check     │  │
│  │   - Add metadata        │    │   - Publish HighRiskTelemetry     │  │
│  │   - Batch write         │    │   - Trigger detector Lambda       │  │
│  │   - 30-day TTL          │    │                                   │  │
│  └─────────────────────────┘    └───────────────────────────────────┘  │
│           ↓                                   ↓                        │
│     DynamoDB                           EventBridge                     │
│  (Telemetry Table)                    (High-Risk Events)               │
└────────────────────────────────────────────────────────────────────────┘
```

---

## Core Components

### 1. TelemetryValidator

Validates incoming telemetry records:

```python
class TelemetryValidator:
    REQUIRED_FIELDS = [
        'sensor_id', 'timestamp', 'latitude', 'longitude',
        'moisture_percent', 'geohash'
    ]

    VALIDATION_RULES = {
        'moisture_percent': (0, 100),
        'tilt_x_degrees': (-30, 30),
        'tilt_y_degrees': (-30, 30),
        'pore_pressure_kpa': (-100, 50),
        'battery_percent': (0, 100),
        'temperature_c': (-10, 50),
        'latitude': (-90, 90),
        'longitude': (-180, 180),
        'vibration_count': (0, 1000),
        'safety_factor': (0, 10),
        'tilt_rate_mm_hr': (0, 50),
    }

    @classmethod
    def validate(cls, telemetry: Dict) -> Tuple[bool, Optional[str]]:
        """Validate telemetry record. Returns (is_valid, error_message)."""
```

**Validation Checks:**
- Required fields present
- Timestamp is valid Unix epoch or ISO 8601 string
- Timestamp in valid range (2020-01-01 to 2038-01-19)
- sensor_id is string with length ≥ 3
- Numeric fields within defined ranges
- geohash is string with length ≥ 4

### 2. NDISEnricher

Enriches telemetry with hazard zone data from NDIS:

```python
class NDISEnricher:
    """Enrich telemetry with hazard-zone data using GeoHashIndex."""

    HAZARD_RANK = {"Very High": 4, "High": 3, "Moderate": 2, "Low": 1, "Unknown": 0}

    def get_hazard_zone(self, geohash: str, latitude: float, longitude: float) -> Optional[Dict]:
        """
        Query hazard zones by geohash4, then refine using bounding box containment.
        Returns highest-risk zone if multiple candidates found.
        """

    def enrich_telemetry(self, telemetry: Dict) -> Dict:
        """Add ndis_enrichment field to telemetry."""
```

**Enrichment Fields Added:**
- `hazard_level` - Very High, High, Moderate, Low
- `hazard_zone_id` - NDIS zone identifier
- `district` - Administrative district
- `ds_division` - Divisional Secretariat
- `gn_division` - Grama Niladhari division
- `landslide_type` - Type of landslide risk
- `soil_type` - Soil classification
- `enriched` - Boolean flag

### 3. TelemetryWriter

Writes validated telemetry to DynamoDB:

```python
class TelemetryWriter:
    def convert_floats_to_decimal(self, obj):
        """Recursively convert floats to Decimal for DynamoDB."""

    def add_metadata(self, telemetry: Dict) -> Dict:
        """Add ingested_at timestamp and 30-day TTL."""

    def write_batch(self, telemetry_batch: List[Dict]) -> Dict:
        """Batch write to DynamoDB. Returns stats dict."""
```

**Metadata Added:**
- `ingested_at` - ISO 8601 timestamp
- `ttl` - Unix timestamp for 30-day expiry

### 4. EventBridgePublisher

Publishes high-risk events for downstream processing:

```python
class EventBridgePublisher:
    HIGH_RISK_THRESHOLDS = {
        'moisture_percent': 85,
        'pore_pressure_kpa': 10,
        'tilt_rate_mm_hr': 5,
        'safety_factor': 1.2
    }

    @classmethod
    def is_high_risk(cls, telemetry: Dict) -> bool:
        """Check if telemetry exceeds high-risk thresholds."""

    @classmethod
    def publish_event(cls, telemetry: Dict) -> None:
        """Publish HighRiskTelemetry event to EventBridge."""
```

**High-Risk Conditions:**
- moisture_percent ≥ 85%
- pore_pressure_kpa ≥ 10 kPa
- tilt_rate_mm_hr ≥ 5 mm/hr
- safety_factor < 1.2 (and > 0)
- hazard_level is High/Very High AND moisture_percent > 70%

---

## Geohash Neighbor Support

The Lambda includes a custom geohash neighbor implementation for spatial queries:

```python
def geohash_neighbors_8(geohash6: str) -> List[str]:
    """Return center cell plus 8 surrounding neighbors."""
    top = _adjacent(geohash6, "top")
    bottom = _adjacent(geohash6, "bottom")
    right = _adjacent(geohash6, "right")
    left = _adjacent(geohash6, "left")

    return list({
        geohash6,
        top, bottom, right, left,
        _adjacent(top, "right"),
        _adjacent(top, "left"),
        _adjacent(bottom, "right"),
        _adjacent(bottom, "left"),
    })
```

---

## Input/Output Schemas

### Input Schema

```json
{
  "telemetry": [
    {
      "sensor_id": "SENSOR_001",
      "timestamp": 1735430400,
      "latitude": 6.85,
      "longitude": 80.93,
      "geohash": "tc1xyz",
      "moisture_percent": 75.5,
      "tilt_x_degrees": 0.5,
      "tilt_y_degrees": 0.3,
      "pore_pressure_kpa": 5.2,
      "vibration_count": 12,
      "battery_percent": 85,
      "temperature_c": 24.5,
      "safety_factor": 1.8,
      "tilt_rate_mm_hr": 2.1
    }
  ]
}
```

**Timestamp Formats Accepted:**
- Unix epoch (integer): `1735430400`
- ISO 8601 string: `"2024-12-29T00:00:00Z"`
- ISO 8601 with timezone: `"2024-12-29T00:00:00+00:00"`

### Output Schema

```json
{
  "message": "Telemetry processed",
  "statistics": {
    "total_received": 25,
    "validated": 24,
    "validation_errors": 1,
    "written_to_dynamodb": 24,
    "write_failures": 0,
    "high_risk_events": 3
  },
  "validation_errors": [
    {
      "index": 5,
      "sensor_id": "SENSOR_006",
      "error": "moisture_percent=105 out of range [0, 100]"
    }
  ]
}
```

### DynamoDB Item (After Processing)

```json
{
  "sensor_id": "SENSOR_001",
  "timestamp": 1735430400,
  "latitude": 6.85,
  "longitude": 80.93,
  "geohash": "tc1xyz",
  "moisture_percent": 75.5,
  "tilt_x_degrees": 0.5,
  "tilt_y_degrees": 0.3,
  "pore_pressure_kpa": 5.2,
  "vibration_count": 12,
  "battery_percent": 85,
  "temperature_c": 24.5,
  "safety_factor": 1.8,
  "tilt_rate_mm_hr": 2.1,
  "ndis_enrichment": {
    "hazard_level": "High",
    "hazard_zone_id": "NSDI_12345",
    "district": "Badulla",
    "ds_division": "Haldummulla",
    "gn_division": "Meeriyabedda",
    "landslide_type": "Debris flow",
    "soil_type": "Colluvium"
  },
  "enriched": true,
  "ingested_at": "2024-12-29T00:00:00",
  "ttl": 1738022400
}
```

### EventBridge Event (High-Risk)

```json
{
  "Source": "openlews.ingestor",
  "DetailType": "HighRiskTelemetry",
  "Detail": {
    "sensor_id": "SENSOR_001",
    "timestamp": 1735430400,
    "latitude": 6.85,
    "longitude": 80.93,
    "moisture_percent": 88.5,
    "pore_pressure_kpa": 12.3,
    "safety_factor": 1.1,
    "hazard_level": "High",
    "alert_reason": "Critical thresholds exceeded"
  },
  "EventBusName": "openlews-events"
}
```

---

## Configuration

### Environment Variables

```bash
# Tables
TELEMETRY_TABLE=openlews-dev-telemetry
HAZARD_ZONES_TABLE=openlews-dev-hazard-zones

# EventBridge
EVENT_BUS=openlews-events

# Feature Flags
ENABLE_NDIS_ENRICHMENT=true
ENABLE_EVENTBRIDGE=true

# Hazard Zone Index
HAZARD_GEOHASH_INDEX=GeoHashIndex
HAZARD_GEOHASH_KEY=geohash

# Logging
LOG_LEVEL=INFO
```

### Feature Flags

| Flag | Default | Description |
|------|---------|-------------|
| ENABLE_NDIS_ENRICHMENT | true | Query NDIS hazard zones for context |
| ENABLE_EVENTBRIDGE | true | Publish high-risk events |

---

## Processing Flow

```
1. Parse Event
   ├── API Gateway: Extract body from event['body']
   └── Direct invoke: Use event directly

2. For each telemetry record:
   ├── Validate (TelemetryValidator)
   │   ├── Pass → Continue
   │   └── Fail → Add to validation_errors, skip
   │
   ├── Enrich (NDISEnricher) if ENABLE_NDIS_ENRICHMENT
   │   ├── Query by geohash4
   │   ├── Filter by bounding box containment
   │   └── Pick highest-risk zone
   │
   └── Check High-Risk (EventBridgePublisher) if ENABLE_EVENTBRIDGE
       └── Publish to EventBridge if thresholds exceeded

3. Batch Write to DynamoDB (TelemetryWriter)
   ├── Convert floats to Decimal
   ├── Add ingested_at and ttl
   └── Batch write with error handling

4. Return Response
   └── Statistics and any errors
```

---

## Error Handling

| Error | Handling |
|-------|----------|
| Missing required field | Skip record, add to validation_errors |
| Value out of range | Skip record, add to validation_errors |
| Invalid timestamp | Skip record, add to validation_errors |
| DynamoDB write failure | Log error, continue with other records |
| EventBridge publish failure | Log error, continue processing |
| NDIS query failure | Log error, skip enrichment for record |

---

## Caching

The NDISEnricher caches hazard zone queries by geohash4:

```python
class NDISEnricher:
    def __init__(self, hazard_table):
        self.cache = {}  # geohash4 -> list of zones
    
    def get_hazard_zone(self, geohash: str, ...):
        geohash4 = geohash[:4]
        
        # Check cache first
        zones = self.cache.get(geohash4)
        if zones is None:
            # Query DynamoDB
            zones = self._query_hazard_zones(geohash4)
            self.cache[geohash4] = zones
```

Cache is per-invocation (Lambda execution context). For batch processing of sensors in the same area, this significantly reduces DynamoDB queries.

---

## Dependencies

```
# Ingestor Lambda Dependencies
# Note: boto3 is pre-installed in Lambda runtime
```

No additional dependencies required - uses only boto3 which is included in the Lambda runtime.

---

## Testing

### Local Testing

```python
from ingestor_lambda import lambda_handler

event = {
    "telemetry": [
        {
            "sensor_id": "TEST_001",
            "timestamp": 1735430400,
            "latitude": 6.85,
            "longitude": 80.93,
            "geohash": "tc1xyz",
            "moisture_percent": 75.5
        }
    ]
}

response = lambda_handler(event, None)
print(response)
```

### Validation Testing

```python
from ingestor_lambda import TelemetryValidator

# Valid record
valid, error = TelemetryValidator.validate({
    "sensor_id": "TEST_001",
    "timestamp": 1735430400,
    "latitude": 6.85,
    "longitude": 80.93,
    "geohash": "tc1xyz",
    "moisture_percent": 75.5
})
assert valid is True

# Invalid record (moisture out of range)
valid, error = TelemetryValidator.validate({
    "sensor_id": "TEST_001",
    "timestamp": 1735430400,
    "latitude": 6.85,
    "longitude": 80.93,
    "geohash": "tc1xyz",
    "moisture_percent": 105  # Invalid
})
assert valid is False
assert "out of range" in error
```

---

## Monitoring

### CloudWatch Metrics

- Invocation count
- Duration
- Error count
- Throttles

### Custom Logging

```python
logger.info(f"Processing {len(telemetry_batch)} telemetry records")
logger.warning(f"Validation failed for record {idx}: {error_msg}")
logger.error(f"Failed to write {item.get('sensor_id')}: {e}")
logger.info(f"Published high-risk event for {telemetry['sensor_id']}")
```

### Key Log Messages

- `"Processing {n} telemetry records"` - Start of processing
- `"Validation failed for record {idx}"` - Validation error
- `"No hazard zone candidates found for geohash4={gh}"` - Enrichment miss
- `"Published high-risk event for {sensor_id}"` - EventBridge publish
- `"Processing complete: {statistics}"` - End of processing

---

## Related Components

- [Detection Engine](../detector/README.md) - Consumes EventBridge events
- [RAG Query Engine](../rag/README.md) - Alternative hazard zone lookup
- [NDIS Data Ingestion](../../data_ingestion/NSDI/README.md) - Hazard zone data source