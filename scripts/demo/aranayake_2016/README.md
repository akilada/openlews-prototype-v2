# Aranayake 2016 Landslide Demo Script

**OpenLEWS Demonstration - Simulating the May 17, 2016 Aranayake Disaster**

---

## Overview

This demo script simulates the catastrophic Aranayake landslide scenario using the OpenLEWS IoT-LLM framework. It deploys **36 virtual sensors** in a **hybrid Quincunx + Vertical topology** based on the forensic analysis of the actual event.

### Historical Event Facts

| Attribute | Value |
|-----------|-------|
| **Date** | May 17, 2016 |
| **Location** | Kegalle District, Sabaragamuwa Province |
| **Crown Coordinates** | 7.1476°N, 80.4546°E (Samasariya Hill) |
| **Toe Coordinates** | 6.9639°N, 80.4209°E (Pallebage Village) |
| **Rainfall** | 446.5mm over 72 hours |
| **Runout Distance** | ~2km |
| **Casualties** | 127 dead/missing |
| **Villages Destroyed** | Siripura, Elangapitiya, Pallebage |

---

## Sensor Topology

The script deploys sensors in a **hybrid topology** specifically designed to capture the failure characteristics noted in the JICA forensic report:

```
                                    ▲ CROWN ZONE (~600m)
                                   /│\  Samasariya Hill
                                  ○ ○ ○     ← 3×3 Quincunx @ 15m (9 sensors)
                                 ○ ○ ○        C01-C09
                                  ○ ○ ○
                                 /     \
                                /       \
                               /  MAIN SCARP (~400m)
                              /   "Unusual Width"   \
                           ○ ○ ○ ○      │      ← 4×3 Quincunx @ 15m (12 sensors)
                          ○ ○ ○ ○       │● 2m    M01-M12
                           ○ ○          │● 5m  ← Vertical Borehole (3 sensors)
                          /             │● 10m   V01-V03
                         /               \
                        /  DEBRIS CHANNEL (~200m)
                       /                  \
                      ○ ○ ○                ← 3×3 Quincunx @ 15m (9 sensors)
                     ○ ○ ○                   D01-D09
                      ○ ○ ○
                     /      \
                    /        \
                   /  TOE/VILLAGE ZONE (~50m)
                  /   Pallebage Village      \
                 ○   ○   ○                    ← 1×3 Line @ 20m (3 sensors)
              ═══════════════════════════════   T01-T03
                   ~2km runout distance

LEGEND: ○ = Surface Sensor   ● = Borehole Sensor   ▲ = Crown
TOTAL:  36 sensors (Hybrid Quincunx + Vertical topology)
SPACING: 15-20m ensures all sensors within 50m correlation radius
```

### Why Hybrid Topology?

1. **Quincunx Pattern**: Staggered grid ensures any linear feature (crack, water flow path) must intercept a sensor
2. **Vertical Borehole**: Captures soil-bedrock interface where the perched water table forms
3. **Zone Coverage**: Matches the ~2km runout from crown to toe

### Spacing Design (FusionAlgorithm Compatibility)

The sensor spacing (15-20m) is specifically chosen to work with the `FusionAlgorithm` parameters:

| Parameter | Value | Implication |
|-----------|-------|-------------|
| `CORRELATION_RADIUS_M` | 50m | Sensors must be within 50m to correlate |
| `CLUSTER_RADIUS_M` | 50m | Cluster detection requires 3+ sensors in 50m |
| `MIN_CLUSTER_SIZE` | 3 | Minimum sensors for cluster alert |

With 15m spacing in a 3×3 quincunx, the maximum diagonal distance is ~37m, ensuring all sensors within each zone can form proper clusters and spatial correlations.

---

## Usage

### Basic Usage

```bash
# Run full demo (all 6 steps)
python demo_aranayake_2016.py
```

### Options

```bash
# Skip detector invocation (just ingest telemetry)
python demo_aranayake_2016.py --skip-detector

# Skip CloudWatch logs display
python demo_aranayake_2016.py --skip-logs

# Clean up demo data after run
python demo_aranayake_2016.py --cleanup

# Reduce output verbosity
python demo_aranayake_2016.py --quiet

# Custom AWS configuration
python demo_aranayake_2016.py \
  --region ap-southeast-2 \
  --telemetry-table openlews-dev-telemetry \
  --alerts-table openlews-dev-alerts \
  --detector-lambda openlews-dev-detector
```

### Environment Variables

The script reads from environment variables (with defaults):

| Variable | Default | Description |
|----------|---------|-------------|
| `AWS_REGION` | `ap-southeast-2` | AWS region |
| `TELEMETRY_TABLE` | `openlews-dev-telemetry` | Telemetry DynamoDB table |
| `ALERTS_TABLE` | `openlews-dev-alerts` | Alerts DynamoDB table |
| `HAZARD_ZONES_TABLE` | `openlews-dev-hazard-zones` | NDIS hazard zones table |
| `DETECTOR_LAMBDA` | `openlews-dev-detector` | Detector Lambda function |
| `RAG_LAMBDA` | `openlews-dev-rag-query` | RAG Query Lambda function |

---

## Demo Steps

The script executes 6 steps:

### Step 1: Sensor Deployment Generation
- Generates 36 sensor positions using hybrid topology
- Calculates coordinates along the 2km slope profile
- Displays ASCII slope diagram

### Step 2: Telemetry Generation (Hour 68 of 72)
- Generates crisis-level sensor readings
- Simulates conditions 4 hours before actual failure
- Key metrics:
  - Moisture: 85-98% (Critical threshold: 40%)
  - Tilt rate: 5-8 mm/hr (Aranayake signature)
  - Pore pressure: +12-17 kPa (positive = unstable)
  - Vibration: 30-50 events/hr (5x baseline)
  - Safety factor: 0.85-1.0 (failure imminent)

### Step 3: Telemetry Ingestion → DynamoDB
- Batch writes all 36 sensor readings
- Adds metadata (ingested_at, TTL)
- Verifies ingestion success

### Step 4: Detector Lambda Invocation
- Invokes the detection engine
- Triggers:
  - RiskScorer (individual sensor analysis)
  - FusionAlgorithm (spatial correlation)
  - Cluster detection (3+ sensors in proximity)
  - RAG query (geological context)
  - Bedrock LLM (risk assessment + narrative)
  - AlertManager (alert creation)

### Step 5: Alert Verification
- Queries alerts table for generated alerts
- Displays:
  - Alert ID, Risk Level, Status, Confidence
  - LLM reasoning
  - Generated narrative
  - Google Maps location

### Step 6: CloudWatch Logs
- Displays recent logs from detector Lambda
- Highlights:
  - RAG queries
  - Bedrock invocations
  - Alert creation events

---

## Expected Output

When running successfully, you should see:

1. **Cluster Detection**: Multiple sensors triggering high-risk patterns
2. **Risk Level**: Orange or Red alert
3. **LLM Narrative**: Evacuation warning mentioning:
   - Soil saturation levels
   - Tilt acceleration
   - Historical parallels (Aranayake 2016)
   - Recommended action (Evacuate immediately)

### Sample Alert

```
Alert ID:      ALERT_20241229_120000_CLUSTER_ARANAYAKE_M01
Risk Level:    🔴 Red
Confidence:    0.94
Status:        active
Time to Failure: hours
Recommended Action: Evacuate immediately

Narrative:
URGENT LANDSLIDE WARNING - KEGALLE SECTOR

SITUATION: Soil moisture sensors show 95% saturation in the main 
scarp zone. Tilt sensors detect 6.5mm/hr displacement - matching 
the pre-failure signature of the 2016 Aranayake disaster.

RISK: High probability of rapid debris flow within 2-6 hours.

ACTION REQUIRED: Immediate evacuation of all residents in 
Siripura, Elangapitiya, and Pallebage. Proceed to designated 
community center at Hathgampola Temple.

ISSUED: 2024-12-29 12:00 UTC
CONTACT: NBRO Emergency Hotline 117
```

---

## Troubleshooting

### No Alerts Generated

**Possible causes:**

1. **Bedrock Rate Limiting**
   - Check CloudWatch logs for throttling errors
   - Wait 60 seconds and retry

2. **Alert Deduplication**
   - Existing alert may prevent new creation
   - Check alerts table for active alerts with same prefix

3. **RAG Query Failure**
   - Ensure hazard zones table has Kegalle data
   - Check RAG Lambda logs

### Detector Timeout

- The detector has a 30-second timeout by default
- Bedrock calls may take 5-10 seconds each
- Consider running `--skip-logs` to reduce processing

### DynamoDB Errors

- Ensure IAM role has `dynamodb:PutItem`, `dynamodb:GetItem`, `dynamodb:Scan`
- Check table exists in correct region

---

## Dependencies

```
boto3>=1.34.0
```

No additional dependencies required - uses only boto3 which should be available in most AWS environments.

For local development:
```bash
pip install boto3
```

---

## Related Components

- [Detection Engine](src/lambdas/detector/README.md)
- [RAG Query Engine](src/lambdas/rag/README.md)
- [Telemetry Ingestor](src/lambdas/telemetry_ingestor/README.md)
- [NDIS Data Ingestion](src/data_ingestion/NSDI/README.md)

---

## References

1. JICA Survey Team (2016). Survey results of Aranayake Disaster
2. Petley, D. (2016). The Aranayake landslide disaster in Sri Lanka. AGU Landslide Blog
3. NBRO. Landslide Hazard Zonation Mapping Programme