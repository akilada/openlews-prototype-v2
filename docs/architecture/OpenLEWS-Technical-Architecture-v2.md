# OpenLEWS Technical Architecture Document

**Open Landslide Early Warning System**  
*A Neuro-Symbolic IoT-LLM Framework for Landslide Prediction in Sri Lanka's Central Highlands*

**Version 2.0 | December 2025**
**Author - Akila Amarathunga**
---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Architecture](#2-system-architecture)
3. [Component Details](#3-component-details)
4. [Alert System](#4-alert-system)
5. [Infrastructure](#5-infrastructure)
6. [Historical Event Calibration](#6-historical-event-calibration)
7. [Future Development Roadmap](#7-future-development-roadmap)
8. [Appendices](#8-appendices)

---

## 1. Executive Summary

OpenLEWS is a research prototype integrating IoT sensor networks with neuro-symbolic AI to provide site-specific landslide monitoring for Sri Lanka's Central Highlands.

### 1.1 Problem Statement

Current NBRO early warning systems rely on regional rainfall thresholds (75/100/150mm) that:
- Cannot account for localized geotechnical conditions
- Result in false positives ("cry wolf" syndrome) or missed events
- Use rainfall as a proxy rather than measuring actual slope stability parameters

### 1.2 Solution Overview

1. **Multi-Sensor Fusion:** Soil moisture, tilt, vibration, pore pressure, safety factor
2. **Neuro-Symbolic AI:** Weighted risk scoring with rule-based geological reasoning
3. **RAG-Enhanced Context:** NSDI geological hazard zone data retrieval
4. **LLM Alert Generation:** Context-aware warnings via Amazon Bedrock (Claude 3 Haiku)

---

## 2. System Architecture

### 2.1 Architecture Layers

| Layer | Components |
|-------|------------|
| **Presentation** | ThingsBoard, React Dashboard (future), SNS Notifications |
| **Application** | Telemetry Ingestor, Detection Engine, RAG Query Lambdas |
| **Data** | DynamoDB, Pinecone Vector DB, S3, Secrets Manager |
| **Intelligence** | Amazon Bedrock, Amazon Location Service, Fusion Algorithm |
| **Simulation** | Python IoT Emulator, Historical Disaster Scenarios |

### 2.2 Data Flow

1. **Ingestion:** Sensors → API Gateway → Telemetry Ingestor → DynamoDB + EventBridge
2. **Detection:** EventBridge Schedule → Detection Engine → Risk Scoring → Cluster Detection
3. **Context:** Detection Engine → RAG Query Lambda → Geological Context
4. **Assessment:** Detection Engine → Bedrock Claude → Risk Assessment + Narrative
5. **Alerting:** Alert Manager → DynamoDB Alerts + SNS Notifications

---

## 3. Component Details

### 3.1 Telemetry Ingestor Lambda

| Component | Function |
|-----------|----------|
| **TelemetryValidator** | Required fields, range checks, timestamp normalization |
| **NSDIEnricher** | Geohash4 lookup, bounding box containment, highest-risk zone selection |
| **TelemetryWriter** | Batch writes, float-to-Decimal, 30-day TTL |
| **EventBridgePublisher** | High-risk event publishing (moisture ≥85%, pore ≥10kPa, tilt ≥5mm/hr, SF <1.2) |

### 3.2 Detection Engine Lambda

#### Risk Scorer Weights

| Component | Weight | Thresholds |
|-----------|--------|------------|
| Soil Moisture | 35% | Relative to critical threshold from RAG |
| Tilt Velocity | 25% | 1/5/10 mm/hr |
| Vibration | 15% | 2x/5x/10x baseline |
| Pore Pressure | 15% | Negative/5kPa/10kPa |
| Safety Factor | 10% | <1.5/<1.2/<1.0 |

**Rainfall Amplifier:** 1.0-1.5x based on NBRO thresholds (75/100/150/200mm)

#### Fusion Algorithm

- **Spatial Correlation:** Neighbours within 50m radius
- **High correlation (>0.6):** Boost risk 1.3x
- **Low correlation (<0.3):** Reduce risk 0.5x
- **Cluster Detection:** 3+ high-risk sensors within 50m

#### Bedrock Client

- Risk Assessment → JSON (risk_level, confidence, reasoning)
- Narrative Generation → Evacuation alerts for Orange/Red
- Retry Logic → Exponential backoff, 6 attempts

#### Alert Manager

- Creation, Deduplication, Escalation (Yellow→Orange→Red)
- SNS Publishing with Google Maps URL
- 30-day TTL

### 3.3 RAG Query Lambda

| Query Type | Description |
|------------|-------------|
| **nearest** | Find single nearest zone (geohash4 + 8 neighbors, Haversine) |
| **radius** | Find all zones within radius, sorted by distance |
| **semantic** | Vector search via Pinecone (placeholder) |

**Critical Moisture Estimation:** Colluvium 35%, Residual 45%, Fill 30%, Bedrock 60%

### 3.4 NSDI Data Ingestion Pipeline

| Component | Function |
|-----------|----------|
| **NSDIDownloader** | ArcGIS REST API, 1000 records/batch, bounds filtering |
| **GeoJSONProcessor** | Centroid, geohash4/6, hazard normalization, bounding box |
| **EmbeddingGenerator** | all-MiniLM-L6-v2, 384 dimensions |
| **DynamoDBIngester** | Batch writes (25 items), <400KB validation |
| **PineconeIngester** | Vector upserts (100/batch), metadata |

**Statistics:** 19,000+ zones for Badulla. Distribution: High 42.8%, Moderate 35.8%, Low 12.8%, Very High 8.6%

---

## 4. Alert System

### 4.1 Alert Levels

| Level | Risk Score | Trigger | Action |
|-------|------------|---------|--------|
| 🟢 **Green** | < 0.4 | Normal | Log data (15 min) |
| 🟡 **Yellow** | 0.4-0.6 | Single indicators | Monitor closely |
| 🟠 **Orange** | 0.6-0.8 | Multiple indicators, correlation | Prepare evacuation |
| 🔴 **Red** | > 0.8 | Critical thresholds, cluster | Evacuate immediately |

### 4.2 Alert Schema

- **Identification:** alert_id, created_at, status, detection_type
- **Risk Assessment:** risk_level, confidence, llm_reasoning, trigger_factors
- **Location:** latitude, longitude, google_maps_url, Amazon Location label
- **Geological Context:** hazard_level, soil_type, critical_moisture, district
- **Cluster Data:** cluster_size, sensors_affected, center_location
- **History:** escalation_history with timestamps and reasons
- **Narrative:** narrative_english for Orange/Red alerts

---

## 5. Infrastructure

### 5.1 Terragrunt/OpenTofu Structure

```
infrastructure/
├── terragrunt.hcl              # Root config
├── environments/
│   ├── dev/
│   │   ├── env.hcl             # Environment variables
│   │   └── terragrunt.hcl      # Environment config
│   ├── uat/
│   └── prod/
└── modules/
    ├── all/                    # Orchestrator
    ├── budgets/
    ├── dynamodb/
    ├── s3/
    ├── secrets/
    ├── location/
    └── lambda/
        ├── detector/
        ├── rag_query/
        └── telemetry_ingestor/
```

### 5.2 Module Inventory

| Module | Resources |
|--------|-----------|
| budgets | AWS Budgets ($15/month limit) |
| dynamodb | Telemetry, Hazard Zones, Alerts tables + GSIs |
| s3 | Lambda artifacts bucket |
| secrets | Pinecone API key |
| location | Amazon Location Place Index |
| lambda/rag_query | Lambda, IAM, CloudWatch |
| lambda/telemetry_ingestor | Lambda, API Gateway, API Key |
| lambda/detector | Lambda, EventBridge, SNS, Bedrock permissions |

### 5.3 Development Configuration

| Setting | Value |
|---------|-------|
| AWS Region | ap-southeast-2 |
| Monthly Budget | $15 USD |
| Lambda Memory | 256 MB |
| DynamoDB TTL | 10 days |
| Log Retention | 3 days |
| Bedrock Model | anthropic.claude-3-haiku-20240307-v1:0 |
| Detection Schedule | rate(15 minutes) |
| Risk Threshold | 0.6 |
| API Rate Limit | 50 req/sec |

---

## 6. Historical Event Calibration

### 6.1 Aranayake 2016

- **Location:** Kegalle District, Sabaragamuwa Province
- **Type:** Complex translational debris flow
- **Casualties:** 127 dead/missing
- **Rainfall:** 400mm over 72 hours, 446.5mm 3-day cumulative
- **Key Precursor:** 5mm/hr tilt rate observed 6 hours before failure
- **Algorithm Calibration:** TILT_RATE_MODERATE = 5mm/hr

### 6.2 Meeriyabedda 2014

- **Location:** Haldummulla, Badulla District
- **Type:** Colluvial failure in tea plantation
- **Casualties:** ~37 confirmed, 100+ estimated missing
- **Precursors:** Muddy water in springs, agitated animals, ground noise
- **Key Signature:** 5x baseline vibration/acoustic emissions
- **Algorithm Calibration:** VIBRATION_HIGH = 5x baseline

---

## 7. Future Development Roadmap

### 7.1 Phase 2: Enhanced Geotechnical Modeling

**Soil Water Characteristic Curves (SWCC)**
- Implement full Fredlund SWCC model for matric suction calculation
- Site-specific calibration using NBRO laboratory soil data
- Dynamic critical moisture thresholds based on antecedent conditions

**NBRO Six-Factor Hazard Weighting**
- Full implementation of Weighted Linear Combination methodology
- Factors: Bedrock geology, hydrology, slope angle, overburden, land use, landform
- Integration with RAG for dynamic risk calculation

**Sensor Physics Calibration**
- Capacitive moisture sensor calibration for Red-Yellow Podzolic soils
- MEMS tiltmeter temperature compensation algorithms
- Acoustic emission filtering for soil-specific frequency signatures

### 7.2 Phase 3: Expanded Coverage

**Additional Districts**
- Nuwara Eliya - High elevation tea country
- Ratnapura - Southwest monsoon impact zone
- Kegalle - Aranayake area detailed coverage
- Kalutara - Coastal highland interface

**Historical Scenario Library**
- Additional forensic analysis: Koslanda 2014, Siripura 2003
- Simulation scenarios for each failure type
- Validation suite for detection accuracy benchmarking

### 7.3 Phase 4: Production Readiness

**Real IoT Hardware Integration**
- ESP32-S3 sensor nodes with LoRaWAN connectivity
- Solar power management for monsoon conditions
- IP67 enclosures for tropical deployment
- ThingsBoard integration for device management

**Multilingual Alerts**
- Sinhala narrative generation using fine-tuned models
- Tamil translation for affected communities
- Voice alert generation for accessibility

**Operational Dashboard**
- React-based monitoring interface
- Real-time map visualization with sensor status
- Historical trend analysis and reporting
- Integration with NBRO Digital Twin platform

### 7.4 Phase 5: Advanced AI Features

**Tiered LLM Strategy**
- Tier 1: Llama 3.3 70B for bulk threshold scanning (every 15 min)
- Tier 2: Claude 3 Haiku for multi-sensor fusion + RAG (on anomaly)
- Tier 3: Claude 3.5 Sonnet for complex reasoning (validated threats)

**Semantic RAG Enhancement**
- Full Pinecone semantic search implementation
- Hybrid search combining geohash + vector similarity
- Historical disaster pattern matching

**Time-Series Analysis**
- LSTM/Transformer models for trend prediction
- Inverse velocity method for failure time estimation
- Anomaly detection using time-series foundation models

---

## 8. Appendices

### 8.1 DynamoDB Table Schemas

**Telemetry Table**
- Primary Key: sensor_id (HASH), timestamp (RANGE)
- Attributes: latitude, longitude, geohash, moisture_percent, tilt_x/y_degrees, pore_pressure_kpa, vibration_count, safety_factor
- Enrichment: nsdi_enrichment (hazard_level, zone_id, district, soil_type)
- TTL: 10 days (dev), 30 days (prod)

**Hazard Zones Table**
- Primary Key: zone_id (HASH)
- GSI: GeoHashIndex (geohash HASH)
- Attributes: level, hazard_level, centroid_lat/lon, geohash4, geohash6, district, ds_division, gn_division, soil_type, land_use, landslide_type, bounding_box
- Source: NSDI ArcGIS REST API

**Alerts Table**
- Primary Key: alert_id (HASH), created_at (RANGE)
- GSI: StatusIndex (status HASH)
- Attributes: risk_level, confidence, llm_reasoning, trigger_factors, recommended_action, location, geological_context, escalation_history, narrative_english
- TTL: 30 days

### 8.2 API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /telemetry | Ingest sensor telemetry batch |
| POST | /rag/query | Query hazard zones (nearest/radius) |

### 8.3 Environment Variables

**Telemetry Ingestor Lambda**
- TELEMETRY_TABLE, HAZARD_ZONES_TABLE, EVENT_BUS
- ENABLE_NSDI_ENRICHMENT, ENABLE_EVENTBRIDGE
- HAZARD_GEOHASH_INDEX, HAZARD_GEOHASH_KEY, LOG_LEVEL

**Detection Engine Lambda**
- TELEMETRY_TABLE_NAME, ALERTS_TABLE_NAME, RAG_LAMBDA_ARN, SNS_TOPIC_ARN
- RISK_THRESHOLD, BEDROCK_MODEL_ID, BEDROCK_REGION
- BEDROCK_MAX_TOKENS, BEDROCK_TEMPERATURE, BEDROCK_MAX_ATTEMPTS
- PLACE_INDEX_NAME, LOCATION_REGION, LOCATION_LANGUAGE

**RAG Query Lambda**
- DYNAMODB_TABLE_NAME, GEOHASH_INDEX_NAME, GEOHASH_PRECISION
- PINECONE_API_KEY, PINECONE_INDEX_NAME, PINECONE_NAMESPACE

---

