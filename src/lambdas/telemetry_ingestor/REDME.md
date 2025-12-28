# OpenLEWS Ingestor Lambda

**Purpose**: Ingests sensor telemetry from simulator, validates data quality, enriches with NDIS geological context, and writes to DynamoDB.

---

## 🎯 Features

### 1. **Schema Validation**
- ✅ Required fields check (`sensor_id`, `timestamp`, `latitude`, etc.)
- ✅ Data type validation (numeric ranges, string formats)
- ✅ Range validation (moisture 0-100%, tilt ±30°, etc.)
- ✅ Timestamp format validation (ISO 8601)
- ✅ Geohash validation (6-8 characters)

### 2. **NDIS Enrichment**
- ✅ Geohash-based hazard zone lookup
- ✅ Adds geological context from existing NDIS database:
  - Hazard level (Low/Moderate/High/Very High)
  - District, DS Division, GN Division
  - Landslide type (Debris flow, Rotational, etc.)
  - Soil type (Residual Laterite, Colluvium)
- ✅ In-memory caching for performance

### 3. **DynamoDB Write**
- ✅ Batch writing (25 items per batch)
- ✅ Automatic float→Decimal conversion
- ✅ Metadata addition (`ingested_at`, `ttl`)
- ✅ 30-day TTL for automatic data cleanup

### 4. **EventBridge Trigger**
- ✅ Publishes high-risk events for downstream processing
- ✅ Triggers on:
  - Moisture ≥ 85%
  - Pore pressure ≥ 10 kPa
  - Tilt rate ≥ 5 mm/hr
  - Safety factor < 1.2
  - High/Very High hazard zone + elevated moisture

---

## 📥 Input Format

```json
{
  "telemetry": [
    {
      "sensor_id": "BADULLA_Q01",
      "timestamp": "2025-11-28T08:15:00",
      "latitude": 6.9934,
      "longitude": 81.0550,
      "elevation_m": 680,
      "depth_m": 0.5,
      "geohash": "tepz1234",
      "moisture_percent": 78.5,
      "tilt_x_degrees": 0.85,
      "tilt_y_degrees": 0.68,
      "pore_pressure_kpa": 8.2,
      "vibration_count": 12,
      "battery_percent": 87.3,
      "temperature_c": 28.4,
      "tilt_rate_mm_hr": 3.45,
      "safety_factor": 1.12,
      "signal_quality": "EXCELLENT",
      "anomaly_flag": false
    }
  ]
}
```

---

## 📤 Output Format

### Success Response

```json
{
  "statusCode": 200,
  "body": {
    "message": "Telemetry processed",
    "statistics": {
      "total_received": 25,
      "validated": 25,
      "validation_errors": 0,
      "written_to_dynamodb": 25,
      "write_failures": 0,
      "high_risk_events": 3
    }
  }
}
```

### Error Response

```json
{
  "statusCode": 400,
  "body": {
    "message": "Validation errors",
    "statistics": {
      "total_received": 25,
      "validated": 22,
      "validation_errors": 3
    },
    "validation_errors": [
      {
        "index": 5,
        "sensor_id": "BADULLA_Q05",
        "error": "moisture_percent=150 out of range [0, 100]"
      }
    ]
  }
}
```

---

## 🗄️ DynamoDB Schema

### Telemetry Table

**Table Name**: `lews-sensor-telemetry-dev`

**Primary Key**:
- Partition Key: `sensor_id` (String)
- Sort Key: `timestamp` (String)

**Attributes**:
```
sensor_id            # BADULLA_Q01
timestamp            # 2025-11-28T08:15:00
latitude             # 6.9934
longitude            # 81.0550
elevation_m          # 680
depth_m              # 0.5
geohash              # tepz1234

# Sensor readings
moisture_percent     # 78.5
pore_pressure_kpa    # 8.2
tilt_x_degrees       # 0.85
tilt_y_degrees       # 0.68
vibration_count      # 12
battery_percent      # 87.3
temperature_c        # 28.4
tilt_rate_mm_hr      # 3.45
safety_factor        # 1.12
signal_quality       # EXCELLENT
anomaly_flag         # false

# NDIS Enrichment (added by Lambda)
ndis_enrichment      # Map
  ├─ hazard_level    # High
  ├─ hazard_zone_id  # ZONE_12345
  ├─ district        # Badulla
  ├─ ds_division     # Badulla
  ├─ gn_division     # Badulla Town
  ├─ landslide_type  # Debris Flow
  └─ soil_type       # Residual Laterite
enriched             # true

# Metadata
ingested_at          # 2025-12-25T10:30:00 (auto-added)
ttl                  # 1738233000 (30 days, auto-added)
```

**GSI** (Global Secondary Index):
- `timestamp-index`: For time-range queries across all sensors

---

## ⚙️ Environment Variables

```bash
# DynamoDB Tables
TELEMETRY_TABLE=lews-sensor-telemetry-dev
HAZARD_ZONES_TABLE=lews-hazard-zones-dev

# EventBridge
EVENT_BUS=default

# Feature Flags
ENABLE_NDIS_ENRICHMENT=true
ENABLE_EVENTBRIDGE=true

# Logging
LOG_LEVEL=INFO
```

---

## 🔧 Validation Rules

### Required Fields
```python
REQUIRED_FIELDS = [
    'sensor_id',
    'timestamp',
    'latitude',
    'longitude',
    'moisture_percent',
    'geohash'
]
```

### Numeric Ranges
```python
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
    'safety_factor': (0, 10)
}
```

---

## 🚨 High-Risk Event Thresholds

Events are published to EventBridge when:

```python
HIGH_RISK_THRESHOLDS = {
    'moisture_percent': 85,      # ≥ 85% saturation
    'pore_pressure_kpa': 10,     # ≥ 10 kPa positive pressure
    'tilt_rate_mm_hr': 5,        # ≥ 5 mm/hr movement
    'safety_factor': 1.2         # < 1.2 factor of safety
}

# OR: High/Very High hazard zone + moisture > 70%
```

**EventBridge Event Format**:
```json
{
  "Source": "openlews.ingestor",
  "DetailType": "HighRiskTelemetry",
  "Detail": {
    "sensor_id": "BADULLA_Q01",
    "timestamp": "2025-11-28T08:15:00",
    "moisture_percent": 87.5,
    "pore_pressure_kpa": 12.3,
    "safety_factor": 1.05,
    "hazard_level": "High",
    "alert_reason": "Critical thresholds exceeded"
  }
}
```

---

## 📊 NDIS Enrichment Process

### How It Works

1. **Geohash Lookup**:
   - Extract first 6 characters of geohash (e.g., `tepz12`)
   - Query `lews-hazard-zones-dev` using `GeoHashIndex` GSI

2. **Data Retrieval**:
   - Get hazard zone record from DynamoDB
   - Extract relevant fields (hazard_level, soil_type, etc.)

3. **Cache**:
   - Store result in Lambda's in-memory cache
   - Reuse for subsequent requests (warm starts)

4. **Enrichment**:
   - Add `ndis_enrichment` field to telemetry
   - Set `enriched: true` flag

### Example Enrichment

**Before**:
```json
{
  "sensor_id": "BADULLA_Q01",
  "geohash": "tepz1234",
  "moisture_percent": 78.5
}
```

**After**:
```json
{
  "sensor_id": "BADULLA_Q01",
  "geohash": "tepz1234",
  "moisture_percent": 78.5,
  "ndis_enrichment": {
    "hazard_level": "High",
    "hazard_zone_id": "ZONE_12345",
    "district": "Badulla",
    "ds_division": "Badulla",
    "gn_division": "Badulla Town",
    "landslide_type": "Debris Flow",
    "soil_type": "Residual Laterite"
  },
  "enriched": true
}
```

---

## 🧪 Testing

### Local Testing (without AWS)

```python
import json
from lambda_function import lambda_handler

# Mock event
event = {
    "telemetry": [
        {
            "sensor_id": "TEST_01",
            "timestamp": "2025-12-25T10:00:00",
            "latitude": 6.9934,
            "longitude": 81.0550,
            "geohash": "tepz1234",
            "moisture_percent": 50.0
        }
    ]
}

# Invoke handler
result = lambda_handler(event, None)
print(json.dumps(result, indent=2))
```

### Test with Simulator

```bash
# In simulator directory
python src/simulator.py \
    --location badulla \
    --placement quincunx \
    --scenario ditwah_2025 \
    --output DYNAMODB \
    --duration 1 \
    --speed 3600
```

### Verify in DynamoDB

```bash
aws dynamodb query \
  --table-name lews-sensor-telemetry-dev \
  --key-condition-expression "sensor_id = :sid" \
  --expression-attribute-values '{":sid":{"S":"BADULLA_Q01"}}' \
  --limit 5
```

---

## 📈 Performance Characteristics

**Latency**:
- Cold start: ~500ms
- Warm start: ~50ms
- NDIS enrichment: +20ms (cached: +2ms)

**Throughput**:
- Can handle 1000 requests/second
- Batch size: 25 telemetry records per request

**Cost** (per 1 million telemetry records):
- Lambda invocations: $0.20
- DynamoDB writes: $1.25
- EventBridge events: $0.10
- **Total**: ~$1.55 per million records

---

## 🔒 IAM Permissions Required

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:PutItem",
        "dynamodb:BatchWriteItem"
      ],
      "Resource": "arn:aws:dynamodb:*:*:table/lews-sensor-telemetry-dev"
    },
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:Query"
      ],
      "Resource": [
        "arn:aws:dynamodb:*:*:table/lews-hazard-zones-dev",
        "arn:aws:dynamodb:*:*:table/lews-hazard-zones-dev/index/GeoHashIndex"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "events:PutEvents"
      ],
      "Resource": "arn:aws:events:*:*:event-bus/default"
    },
    {
      "Effect": "Allow",
      "Action": [
        "logs:CreateLogGroup",
        "logs:CreateLogStream",
        "logs:PutLogEvents"
      ],
      "Resource": "arn:aws:logs:*:*:*"
    }
  ]
}
```

---

## 🐛 Troubleshooting

### Issue: "Table not found"

**Solution**: Verify table names in environment variables match actual DynamoDB tables.

### Issue: "NDIS enrichment not working"

**Checks**:
1. Verify `GeoHashIndex` GSI exists on hazard zones table
2. Check geohash format (6-8 characters)
3. Enable debug logging: `LOG_LEVEL=DEBUG`

### Issue: "EventBridge events not triggering"

**Checks**:
1. Verify `ENABLE_EVENTBRIDGE=true`
2. Check IAM permissions for `events:PutEvents`
3. Verify event bus name

---

## 📚 Next Steps

1. **Deploy via Terragrunt** (see deployment guide)
2. **Connect to API Gateway** (POST /telemetry endpoint)
3. **Test with simulator** (send sample telemetry)
4. **Build Detection Lambda** (consumes EventBridge events)

---

**Questions?** Check the main architecture documentation or deployment guide.