# Detection Engine Lambda

**Multi-Modal Sensor Fusion with LLM Reasoning for Landslide Risk Detection**

---

## Overview

The Detection Engine Lambda performs scheduled analysis of sensor telemetry to detect landslide risk. It implements a neuro-symbolic approach combining:

1. **Individual sensor risk scoring** - Based on Mohr-Coulomb mechanics and NBRO thresholds
2. **Spatial correlation analysis** - "Neighbourhood Watch" multi-sensor fusion
3. **Cluster detection** - Identifying groups of high-risk sensors
4. **LLM reasoning** - Claude-powered risk assessment and narrative generation
5. **Alert management** - Creation, deduplication, and escalation

---

## Directory Structure

```
src/lambdas/detector/
├── detector_lambda.py       # Main Lambda handler
├── core/
│   ├── fusion_algorithm.py  # Spatial correlation & cluster detection
│   └── risk_scorer.py       # Individual sensor risk calculation
├── clients/
│   ├── alert_manager.py     # Alert lifecycle management
│   ├── bedrock_client.py    # Amazon Bedrock LLM integration
│   └── rag_client.py        # RAG Query Lambda client
├── utils/
│   ├── telemetry_fetcher.py # DynamoDB telemetry retrieval
│   └── location_resolver.py # Amazon Location Service reverse geocoding
└── requirements.txt
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Detection Engine Lambda                             │
│                                                                             │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                      TelemetryFetcher                                  │ │
│  │  - Query by sensor_id + timestamp range                                │ │
│  │  - Optional GSI queries (hazard_level, geohash)                        │ │
│  │  - Fetch latest per sensor                                             │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                    ↓                                        │
│  ┌─────────────────────────┐    ┌─────────────────────────────────────────┐ │
│  │      RiskScorer         │    │         FusionAlgorithm                 │ │
│  │  - Moisture scoring     │    │  - Spatial correlation                  │ │
│  │  - Tilt velocity        │ →  │  - Composite risk calculation           │ │
│  │  - Vibration analysis   │    │  - Cluster detection (3+ sensors)       │ │
│  │  - Pore pressure        │    │  - Haversine distance                   │ │
│  │  - Safety factor        │    │                                         │ │
│  │  - Rainfall amplifier   │    │                                         │ │
│  └─────────────────────────┘    └─────────────────────────────────────────┘ │
│                                    ↓                                        │
│  ┌─────────────────────────┐    ┌─────────────────────────────────────────┐ │
│  │      RAGClient          │    │      LocationResolver                   │ │
│  │  - Query nearest zone   │    │  - Amazon Location Service              │ │
│  │  - Critical moisture    │    │  - Reverse geocoding                    │ │
│  │  - Hazard level         │    │  - Google Maps URLs                     │ │
│  └─────────────────────────┘    └─────────────────────────────────────────┘ │
│                                    ↓                                        │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                       BedrockClient                                    │ │
│  │  - Risk assessment (JSON output)                                       │ │
│  │  - Narrative generation (evacuation alerts)                            │ │
│  │  - Converse API with retry/backoff                                     │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                    ↓                                        │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                       AlertManager                                     │ │
│  │  - Create new alerts                                                   │ │
│  │  - Deduplication (check existing)                                      │ │
│  │  - Escalation (Yellow → Orange → Red)                                  │ │
│  │  - SNS notification publishing                                         │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Core Components

### 1. RiskScorer (`core/risk_scorer.py`)

Calculates individual sensor risk scores (0.0-1.0) based on geotechnical principles:

```python
class RiskScorer:
    # NBRO rainfall thresholds (mm/24h)
    RAINFALL_YELLOW = 75.0
    RAINFALL_ORANGE = 100.0
    RAINFALL_RED = 150.0
    RAINFALL_CRITICAL = 200.0  # Aranayake-level

    # Tilt rate thresholds (mm/hour)
    TILT_RATE_MINOR = 1.0
    TILT_RATE_MODERATE = 5.0   # Aranayake pre-failure
    TILT_RATE_CRITICAL = 10.0

    # Vibration multipliers (vs baseline)
    VIBRATION_ELEVATED = 2.0
    VIBRATION_HIGH = 5.0       # Meeriyabedda acoustic signature
    VIBRATION_CRITICAL = 10.0

    # Safety Factor thresholds
    SAFETY_FACTOR_CAUTION = 1.5
    SAFETY_FACTOR_WARNING = 1.2
    SAFETY_FACTOR_FAILURE = 1.0

    # Component weights
    WEIGHTS = {
        'moisture': 0.35,
        'tilt_velocity': 0.25,
        'vibration': 0.15,
        'pore_pressure': 0.15,
        'safety_factor': 0.10
    }
```

**Scoring Functions:**

| Component | Method | Thresholds |
|-----------|--------|------------|
| Moisture | `_score_moisture()` | Relative to critical threshold (from RAG) |
| Tilt Velocity | `_score_tilt_velocity()` | 1/5/10 mm/hr |
| Vibration | `_score_vibration()` | 2x/5x/10x baseline |
| Pore Pressure | `_score_pore_pressure()` | Negative=safe, >10kPa=critical |
| Safety Factor | `_score_safety_factor()` | <1.5=caution, <1.2=warning, <1.0=failure |
| Rainfall | `_rainfall_amplification()` | Multiplier 1.0-1.5x based on 24h total |

### 2. FusionAlgorithm (`core/fusion_algorithm.py`)

Implements multi-sensor spatial analysis:

```python
class FusionAlgorithm:
    SENSOR_SPACING_M = 20.0      # Quincunx grid spacing
    CORRELATION_RADIUS_M = 50.0  # 2.5x spacing for neighbours
    MIN_CLUSTER_SIZE = 3         # Minimum sensors for cluster
    CLUSTER_RADIUS_M = 50.0
```

**Key Methods:**

| Method | Purpose |
|--------|---------|
| `calculate_spatial_correlation()` | Count agreeing neighbours (Strategy B: Neighbourhood Watch) |
| `calculate_composite_risk()` | Adjust risk based on correlation (boost if high, reduce if low) |
| `detect_clusters()` | Find groups of 3+ high-risk sensors within radius |
| `_haversine_distance()` | Calculate distance between coordinates |

**Spatial Correlation Logic:**
- High correlation (>0.6): Boost risk by 1.3x (neighbours agree = high confidence)
- Low correlation (<0.3): Reduce risk by 0.5x (likely sensor fault)
- Medium correlation: No adjustment

### 3. BedrockClient (`clients/bedrock_client.py`)

LLM integration using Amazon Bedrock Converse API:

```python
class BedrockClient:
    DEFAULT_MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0"

    SYSTEM_PROMPT = """You are a Senior Geotechnical Engineer at Sri Lanka's 
    National Building Research Organisation (NBRO)..."""
```

**Methods:**

| Method | Purpose | Output |
|--------|---------|--------|
| `assess_risk()` | Analyze sensor data for risk level | JSON with risk_level, confidence, reasoning |
| `generate_narrative()` | Create evacuation alert text | Plain text narrative |
| `_invoke_bedrock()` | Converse API call with retry/backoff | Response text |

**LLM Output Schema:**
```json
{
  "risk_level": "Yellow|Orange|Red",
  "confidence": 0.0-1.0,
  "reasoning": "Technical explanation...",
  "trigger_factors": ["factor1", "factor2"],
  "recommended_action": "Monitor closely|Prepare evacuation|Evacuate immediately",
  "time_to_failure_estimate": "hours|days|unknown",
  "references": ["Aranayake 2016", "NBRO threshold"]
}
```

### 4. RAGClient (`clients/rag_client.py`)

Queries RAG Lambda for geological context:

```python
class RAGClient:
    async def query_nearest(self, latitude: float, longitude: float) -> Dict:
        """Query nearest NSDI hazard zone."""

    def _estimate_critical_moisture(self, hazard_level: str, soil_type: str) -> float:
        """Estimate critical moisture threshold."""
        # Base thresholds by soil type
        base_thresholds = {
            'Colluvium': 35,   # Loose, unstable
            'Residual': 45,    # More stable
            'Fill': 30,        # Very unstable
            'Bedrock': 60      # Very stable
        }
        # Adjust by hazard level (-5 for Very High, +10 for Very Low)
```

**Response Fields:**
- `hazard_level` - Very High, High, Moderate, Low
- `soil_type` - Colluvium, Residual, etc.
- `slope_angle` - Degrees
- `land_use` - Tea, Rubber, Forest
- `distance_m` - Distance to zone
- `critical_moisture_percent` - Calculated threshold
- `district`, `ds_division`, `gn_division` - Administrative areas

### 5. AlertManager (`clients/alert_manager.py`)

Handles alert lifecycle:

```python
class AlertManager:
    RISK_HIERARCHY = {"Yellow": 1, "Orange": 2, "Red": 3}
    ALERT_TTL_SECONDS = 30 * 24 * 3600  # 30 days
```

**Methods:**

| Method | Purpose |
|--------|---------|
| `get_active_alert()` | Check for existing alert (deduplication) |
| `create_alert()` | Create new alert with full metadata |
| `escalate_alert()` | Upgrade risk level, update history |
| `_publish_to_sns()` | Send notification to SNS topic |

**Alert Fields:**
- `alert_id` - `ALERT_YYYYMMDD_HHMMSS_<prefix>`
- `risk_level` - Yellow, Orange, Red
- `confidence` - 0.0-1.0
- `llm_reasoning` - Technical explanation
- `recommended_action` - Action to take
- `narrative_english` - Plain language alert
- `location` - Label, Google Maps URL, address
- `geological_context` - Hazard level, soil type, critical moisture
- `escalation_history` - Level changes over time

### 6. TelemetryFetcher (`utils/telemetry_fetcher.py`)

Efficient DynamoDB telemetry retrieval:

```python
class TelemetryFetcher:
    HAZARD_LEVEL_INDEX = "HazardLevelIndex"
    FAILURE_STAGE_INDEX = "FailureStageIndex"
    SPATIAL_INDEX = "SpatialIndex"
```

**Methods:**

| Method | Purpose |
|--------|---------|
| `fetch_by_time_range()` | Query telemetry within time range |
| `fetch_by_hazard_level()` | Query via HazardLevelIndex GSI |
| `fetch_by_geohash()` | Query via SpatialIndex GSI |
| `fetch_latest_per_sensor()` | Get most recent reading per sensor |
| `fetch_for_analysis_window()` | Get single sensor's recent data |

### 7. LocationResolver (`utils/location_resolver.py`)

Amazon Location Service reverse geocoding:

```python
class LocationResolver:
    def resolve(self, latitude: float, longitude: float) -> Dict:
        """
        Returns:
        {
          "location_label": "...",
          "google_maps_url": "...",
          "google_maps_directions_url": "...",
          "resolved_by": "amazon_location|coordinates_only",
          "address": {...},
          "place": {...}
        }
        """
```

---

## Processing Flow

```
1. EventBridge Trigger (scheduled)
   └── lambda_handler()

2. Fetch Telemetry
   └── fetch_recent_telemetry(hours=24)
       └── TelemetryFetcher.fetch_by_time_range()

3. Analyze Sensors
   └── analyze_sensors()
       ├── For each sensor:
       │   ├── RiskScorer.calculate_sensor_risk()
       │   ├── FusionAlgorithm.calculate_spatial_correlation()
       │   └── FusionAlgorithm.calculate_composite_risk()
       └── FusionAlgorithm.detect_clusters()

4. Process High-Risk Detections
   └── process_high_risk_detections()
       ├── For each cluster (avg_risk > threshold):
       │   └── process_cluster()
       │       ├── LocationResolver.resolve()
       │       ├── RAGClient.query_nearest()
       │       ├── BedrockClient.assess_risk()
       │       ├── BedrockClient.generate_narrative() (if Orange/Red)
       │       └── AlertManager.create_alert() or escalate_alert()
       └── For each individual sensor (composite_risk > threshold, not in cluster):
           └── process_individual_sensor()
               └── (same as cluster processing)

5. Return Summary
   └── {sensors_analyzed, clusters_detected, alerts_created, alerts_escalated}
```

---

## Configuration

### Environment Variables

```bash
# Required
TELEMETRY_TABLE_NAME=openlews-dev-telemetry
ALERTS_TABLE_NAME=openlews-dev-alerts
RAG_LAMBDA_ARN=arn:aws:lambda:...:rag-query-lambda
SNS_TOPIC_ARN=arn:aws:sns:...:openlews-alerts

# Optional - Risk Threshold
RISK_THRESHOLD=0.6

# Bedrock Configuration
BEDROCK_MODEL_ID=anthropic.claude-3-haiku-20240307-v1:0
BEDROCK_REGION=ap-southeast-2
BEDROCK_MAX_TOKENS=2000
BEDROCK_TEMPERATURE=0.3
BEDROCK_TOP_P=0.9
BEDROCK_BOTO_RETRIES=5
BEDROCK_MAX_ATTEMPTS=6
BEDROCK_BACKOFF_BASE_SEC=0.6

# Amazon Location Service
PLACE_INDEX_NAME=openlews-place-index
LOCATION_REGION=ap-south-1
LOCATION_LANGUAGE=en
LOCATION_MAX_RESULTS=1
LOCATION_LABEL_FORMAT=short
```

---

## Alert Levels

| Level | Trigger | Recommended Action |
|-------|---------|-------------------|
| **Yellow** | composite_risk > 0.6, single indicators elevated | Monitor closely |
| **Orange** | Multiple indicators elevated, spatial correlation high | Prepare evacuation |
| **Red** | Critical thresholds exceeded, cluster detected | Evacuate immediately |

### Escalation Logic

```python
def should_escalate(existing_alert: Dict, new_assessment: Dict) -> bool:
    # Escalate if risk level increased
    if risk_hierarchy[new_level] > risk_hierarchy[current_level]:
        return True
    
    # Escalate if confidence significantly increased (>0.15) at same level
    if (new_level == current_level and 
        new_assessment['confidence'] > existing_alert['confidence'] + 0.15):
        return True
    
    return False
```

---

## Input/Output Schemas

### Lambda Input (EventBridge Scheduled)

```json
{
  "source": "aws.events",
  "detail-type": "Scheduled Event",
  "detail": {}
}
```

### Lambda Output

```json
{
  "statusCode": 200,
  "body": {
    "status": "success",
    "sensors_analyzed": 25,
    "clusters_detected": 1,
    "alerts_created": 2,
    "alerts_escalated": 0,
    "execution_time": 4.532,
    "timestamp": "2024-12-29T00:00:00"
  }
}
```

### DynamoDB Alert Item

```json
{
  "alert_id": "ALERT_20241229_120000_CLUSTER_SENSOR_001",
  "created_at": 1735430400,
  "updated_at": 1735430400,
  "status": "active",
  "risk_level": "Orange",
  "confidence": 0.85,
  "llm_reasoning": "Soil moisture (82%) exceeds critical threshold...",
  "trigger_factors": ["High moisture", "Spatial correlation", "Colluvium soil"],
  "recommended_action": "Prepare evacuation",
  "time_to_failure": "hours",
  "references": ["Aranayake 2016", "NBRO threshold"],
  "narrative_english": "URGENT LANDSLIDE WARNING...",
  "detection_type": "cluster",
  "cluster_size": 4,
  "sensors_affected": ["SENSOR_001", "SENSOR_002", "SENSOR_003", "SENSOR_004"],
  "center_location": {"lat": 6.85, "lon": 80.93},
  "latitude": 6.85,
  "longitude": 80.93,
  "google_maps_url": "https://www.google.com/maps/search/?api=1&query=6.850000,80.930000",
  "location": {
    "label": "Haldummulla, Badulla, Sri Lanka",
    "google_maps_url": "...",
    "resolved_by": "amazon_location",
    "address": {
      "municipality": "Haldummulla",
      "region": "Uva",
      "country": "Sri Lanka"
    }
  },
  "geological_context": {
    "hazard_level": "High",
    "soil_type": "Colluvium",
    "critical_moisture": 35
  },
  "escalation_history": [
    {"timestamp": 1735430400, "from_level": "NONE", "to_level": "Orange", "reason": "Initial alert"}
  ],
  "ttl": 1738022400
}
```

---

## Historical Event References

The LLM system prompt and scoring are calibrated against:

### Aranayake 2016
- Complex translational debris flow
- 400mm rainfall over 72 hours
- 5mm/hr tilt rate observed 6 hours before failure
- 127 casualties

### Meeriyabedda 2014
- Colluvial failure in tea plantation
- Acoustic emissions (5x baseline) detected before failure
- Animals agitated, ground noise reported
- ~37 confirmed casualties

---

## Dependencies

```
boto3>=1.34.0
aws-lambda-powertools[tracer]>=2.30.0
requests>=2.31.0
botocore
pinecone>=7.3.0
pygeohash>=3.2.0
aws-xray-sdk>=2.12.0
```

---

## Testing

### Unit Tests

```bash
pytest tests/detector/unit/ -v
```

### Scenario Tests

```bash
# Test Aranayake-like scenario
pytest tests/detector/scenarios/test_aranayake.py -v

# Test sensor fault detection
pytest tests/detector/scenarios/test_sensor_fault.py -v
```

### Manual Testing

```python
from detector_lambda import lambda_handler

# Simulate scheduled event
event = {
    "source": "aws.events",
    "detail-type": "Scheduled Event"
}

response = lambda_handler(event, None)
print(response)
```

---

## Monitoring

### CloudWatch Metrics (via Powertools)

- Invocation count, duration, errors
- X-Ray traces for full request flow

### Key Log Messages

- `"Starting detector analysis"` - Lambda start
- `"Analyzing {n} sensors"` - Analysis phase
- `"Cluster detected: {sensor_id}"` - Cluster found
- `"Processing high-risk cluster/sensor"` - LLM processing
- `"Creating new alert"` / `"Escalating alert"` - Alert actions
- `"Detection complete"` - Lambda end with summary

---

## Error Handling

| Error | Handling |
|-------|----------|
| No telemetry data | Return `status: no_data` |
| RAG Lambda failure | Use default geological context |
| Bedrock throttling | Exponential backoff (up to 6 attempts) |
| Alert write failure | Log error, continue processing |
| SNS publish failure | Log error, alert still created |
| Location resolve failure | Fall back to coordinates only |

---

## Related Components

- [RAG Query Engine](../rag/README.md) - Geological context provider
- [Telemetry Ingestor](../telemetry_ingestor/README.md) - Data source
- [NSDI Data Ingestion](../../data_ingestion/NSDI/README.md) - Hazard zone data