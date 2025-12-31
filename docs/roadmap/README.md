# OpenLEWS Implementation Roadmap

> **Version 2.1** | Last Updated: January 2026
>
> Consolidated response to Neuro-Symbolic Pipeline Review, merging third-party analysis with internal LLM/geologist recommendations.

## Quick Links

- [Success Metrics](#success-metrics)
- [Phase 1: Critical (2-3 weeks)](#phase-1--critical-enhancements-23-weeks)
- [Phase 2: High-Impact (3-4 weeks)](#phase-2--high-impact-enhancements-34-weeks)
- [Phase 3: Medium-Priority (4-6 weeks)](#phase-3--medium-priority-enhancements-46-weeks)
- [Phase 4: Long-Term (8-12 weeks)](#phase-4--long-term-enhancements-812-weeks)
- [Review Cadence](#review-cadence)

---

## Guiding Principles

| Principle | Description |
|-----------|-------------|
| **Reliability** | Timely, well-calibrated alerts via multi-sensor fusion, fault detection, and uncertainty quantification |
| **Interpretability** | Explicit rules for auditable decisions; LLM communicates risk with evidence citations |
| **Adaptivity** | Thresholds and weights adapt to hazard level, soil type, rainfall regime, and season |
| **Modularity** | Phased implementation; each component developed, tested, and deployed independently |

---

## Success Metrics

Each phase has quantitative success criteria. Tasks are complete when these targets are met.

### Alert Quality
| Metric | Target |
|--------|--------|
| False Positive Rate | ≤15% (Yellow), ≤10% (Orange), ≤5% (Red) |
| False Negative Rate | ≤5% for actual landslide events |
| Alert Lead Time | ≥2 hours before failure (median) |

### Trend Detection
| Metric | Target |
|--------|--------|
| Trend R² (valid predictions) | ≥0.7 for trend slopes used in scoring |
| Inverse Velocity R² | ≥0.7 for failure time predictions |
| Trend Detection Latency | ≤30 minutes from onset to detection |

### Sensor Health
| Metric | Target |
|--------|--------|
| Fault Detection Accuracy | ≥90% of stuck/faulty sensors identified |
| Communication Gap Detection | 100% of gaps >3× interval flagged |

### RAG Quality
| Metric | Target |
|--------|--------|
| Hazard Level Query Accuracy | Top-3 results match query intent ≥80% |
| Historical Pattern Match | Relevant event retrieved ≥70% of high-risk cases |

### System Performance
| Metric | Target |
|--------|--------|
| Detection Cycle Time | ≤60 seconds end-to-end |
| Test Coverage | ≥80% for core modules |

---

## Phase 1 – Critical Enhancements (2-3 weeks)

> **Priority:** Critical | **Status:** Not Started
>
> These tasks address the most pressing gaps. Complete before NBRO demonstration.

### 1.1 Time-Series Trend Calculation
<!-- Issue: #TBD -->

**Problem:** TelemetryFetcher retrieves 24-hour window but RiskScorer only uses latest reading. Trend variables in LLM prompt are placeholders.

**Implementation:**
- [ ] Create `TrendAnalyzer` class with linear regression for moisture, tilt, pore pressure
- [ ] Calculate trends over multiple windows (1h, 6h, 24h)
- [ ] Compute tilt acceleration (second derivative)
- [ ] Add trend weights to composite risk formula (~5% each)
- [ ] Integrate into detector pipeline after TelemetryFetcher
- [ ] Update LLM prompt with real trend values

**Deliverables:**
- `core/trend_analyzer.py`
- `tests/unit/test_trend_analyzer.py`
- Updated `detector_lambda.py`

**Success Criteria:** Trend R² ≥0.7; detection latency ≤30 min

---

### 1.2 Sensor Health Monitoring
<!-- Issue: #TBD -->

**Problem:** No detection of stuck sensors, communication failures, or implausible readings.

**Implementation:**
- [ ] Create `SensorHealthChecker` class
- [ ] Implement stuck sensor detection (low variance over N readings)
- [ ] Implement communication gap detection (>3× expected interval)
- [ ] Implement range violation checks (moisture <0% or >100%)
- [ ] Implement spike detection (>3σ from rolling mean)
- [ ] Add `sensor_health` field: HEALTHY, DEGRADED, FAULTY
- [ ] Exclude FAULTY from correlation; reduce DEGRADED weight by 0.5×
- [ ] Add CloudWatch alarm for communication failures

**Deliverables:**
- `core/sensor_health.py`
- `tests/unit/test_sensor_health.py`
- CloudWatch alarm configuration

**Success Criteria:** ≥90% fault detection; 100% gap detection

---

### 1.3 Cross-Modal Consistency Rules
<!-- Issue: #TBD -->

**Problem:** No validation that sensor readings are physically consistent across modalities.

**Cross-Modal Rules:**

| Condition | Interpretation | Action |
|-----------|---------------|--------|
| High moisture + No tilt | Infiltration phase | Monitor closely |
| High tilt + Low moisture | Mechanical disturbance | Reduce risk 0.7× |
| High vibration + No tilt/moisture | External noise | Suppress alert |
| High moisture + tilt + vibration | Active failure | Boost risk 1.3× |
| Rising pore pressure + tilt increasing | Piping/erosion | High confidence precursor |

**Implementation:**
- [ ] Create `CrossModalValidator` class
- [ ] Implement consistency rules table
- [ ] Output `consistency_score` (0-1) that modifies composite risk
- [ ] Add dynamic weight adjustment for rainfall regime
- [ ] Add seasonal weight profiles (monsoon vs. dry)

**Deliverables:**
- `core/cross_modal_validator.py`
- `config/seasonal_weights.yaml`
- `tests/unit/test_cross_modal.py`

---

### 1.4 Rainfall Forecasting Integration
<!-- Issue: #TBD -->

**Problem:** Antecedent rainfall adjustments are reactive. Forecasts can improve lead time by 6-24 hours.

**Implementation:**
- [ ] Create `WeatherForecastClient` class
- [ ] Integrate Sri Lanka Met Dept API or Open-Meteo
- [ ] Implement forecast risk modifiers:
  - Forecast ≥75mm/24h → 1.1× multiplier
  - Forecast ≥100mm/24h → 1.2× multiplier  
  - Forecast ≥150mm/24h → 1.3× multiplier
- [ ] Weight by forecast confidence and time horizon
- [ ] Cache forecasts in DynamoDB (1-hour TTL)
- [ ] Implement graceful fallback if forecast unavailable

**Deliverables:**
- `clients/weather_client.py`
- DynamoDB forecast cache table (Terraform)
- `tests/unit/test_weather_client.py`

**Success Criteria:** ≥95% forecast availability; ≥15% lead time improvement

---

### 1.5 Negative Pore Pressure Handling
<!-- Issue: #TBD -->

**Problem:** System doesn't distinguish genuine negative pore pressure (matric suction) from sensor errors.

**Implementation:**
- [ ] Add plausibility checks to `SensorHealthChecker`:
  - pore_pressure < -50 kPa → likely sensor error (DEGRADED)
  - Negative pore pressure + moisture > 80% → inconsistent, flag for review
  - Stuck at same negative value >6 hours → stuck sensor
- [ ] Add cross-modal rule: genuine suction correlates with low moisture + dry weather
- [ ] Add transition monitoring: rate > 2 kPa/hour triggers elevated alert
- [ ] Add `pore_pressure_status` to LLM context: VALID_SUCTION, VALID_POSITIVE, SUSPECT_ERROR

**Deliverables:**
- Updates to `core/sensor_health.py`
- Updates to `core/cross_modal_validator.py`
- Updates to `clients/bedrock_client.py` prompt

---

## Phase 2 – High-Impact Enhancements (3-4 weeks)

> **Priority:** High | **Status:** Not Started
>
> Builds on Phase 1. Makes the system more intelligent.

### 2.1 Dynamic Threshold Adaptation
<!-- Issue: #TBD -->

**Problem:** Fixed thresholds apply uniformly regardless of context.

**Implementation:**
- [ ] Extend RAG client to return `threshold_modifiers`
- [ ] Implement hazard-level adjustment (lower thresholds in Very High zones)
- [ ] Implement soil-type adjustment (Colluvium triggers at lower moisture)
- [ ] Apply modifiers in RiskScorer before threshold comparison

**Deliverables:**
- Updated `clients/rag_client.py`
- Updated `core/risk_scorer.py`
- `config/threshold_modifiers.yaml`

---

### 2.2 Enhanced RAG Semantic Search
<!-- Issue: #TBD -->

**Problem:** Query "Very High hazard" returns "Low" as top result. Embedding model doesn't capture severity semantics.

**Implementation:**
- [ ] Restructure `generate_embedding_text()` with hazard level first + synonyms
- [ ] Re-index Pinecone vectors with new embedding structure
- [ ] Implement hybrid search (vector + metadata filter)
- [ ] Implement query rewriting utility
- [ ] Begin indexing historical landslide events

**Deliverables:**
- Updated `geo_processor.py`
- Re-indexed Pinecone namespace
- `rag_query_lambda.py` semantic search

**Success Criteria:** Top-3 accuracy ≥80%

---

### 2.3 Evidence Citation and Uncertainty Quantification
<!-- Issue: #TBD -->

**Problem:** LLM outputs lack structured evidence and confidence intervals.

**Enhanced JSON Schema:**
```json
{
  "risk_level": "Orange",
  "confidence": 0.78,
  "evidence_citations": [
    {"sensor": "SENS-001", "metric": "moisture", "value": 82, "threshold": 75, "risk_contribution": 0.35}
  ],
  "time_to_failure": {
    "estimate": "4 hours",
    "confidence_interval": "2-8 hours"
  }
}
```

**Implementation:**
- [ ] Update Bedrock system prompt with evidence schema
- [ ] Add JSON schema validation for LLM response
- [ ] Store `evidence_citations` in alert records

**Deliverables:**
- Updated `clients/bedrock_client.py`
- JSON schema validator
- Updated alert DynamoDB schema

---

### 2.4 Expanded Test Suite and CI
<!-- Issue: #TBD -->

**Implementation:**
- [ ] Unit tests for all Phase 1 & 2 components
- [ ] Integration tests with mocked AWS (moto)
- [ ] GitHub Actions CI pipeline
- [ ] Coverage reporting

**Deliverables:**
- `tests/unit/` - Complete coverage
- `tests/integration/` - AWS mocked tests
- `.github/workflows/ci.yml`

**Success Criteria:** ≥80% coverage for core modules

---

## Phase 3 – Medium-Priority Enhancements (4-6 weeks)

> **Priority:** Medium | **Status:** Not Started

### 3.1 Inverse Velocity Failure Prediction
<!-- Issue: #TBD -->

**Implementation:**
- [ ] Create `InverseVelocityPredictor` class
- [ ] Require 6+ hours of accelerating tilt data
- [ ] Fit linear regression to 1/tilt_rate vs time
- [ ] Extrapolate x-intercept as failure time (if slope negative)
- [ ] Require R² > 0.7 for valid predictions
- [ ] Validate against Aranayake 2016 simulation

**Deliverables:**
- `core/inverse_velocity.py`
- Validation report

**Success Criteria:** R² ≥0.7; validated against simulation

---

### 3.2 Unsupervised Anomaly Detection
<!-- Issue: #TBD -->

**Implementation:**
- [ ] Implement Isolation Forest detector
- [ ] Optionally implement Autoencoder detector
- [ ] Train on historical "normal" telemetry
- [ ] Use anomaly score as 5% weight in composite risk
- [ ] Create training script for offline model updates

**Deliverables:**
- `core/anomaly_detector.py`
- `models/` directory for artifacts
- Training script

---

### 3.3 Simulation Harness Expansion
<!-- Issue: #TBD -->

**Implementation:**
- [ ] Add rotational failure scenario
- [ ] Add translational failure scenario
- [ ] Add debris flow scenario
- [ ] Add piping/internal erosion scenario (Meeriyabedda-style)
- [ ] Add sensor fault scenarios
- [ ] Create validation suite with accuracy benchmarks

**Deliverables:**
- `simulations/scenarios/`
- `simulations/validation_suite.py`
- Scenario documentation

---

### 3.4 Historical Pattern Matching via RAG
<!-- Issue: #TBD -->

**Implementation:**
- [ ] Create `historical_events` Pinecone namespace
- [ ] Embed Aranayake 2016, Meeriyabedda 2014, Koslanda 2014
- [ ] Query when composite risk > 0.5
- [ ] Include similar events in LLM context

**Deliverables:**
- `data/historical_events/`
- Historical event indexing script
- Updated RAG query

**Success Criteria:** Relevant event retrieved ≥70%

---

## Phase 4 – Long-Term Enhancements (8-12 weeks)

> **Priority:** Future | **Status:** Not Started
>
> Requires external dependencies (NBRO collaboration, additional datasets).

### 4.1 NBRO Six-Factor Hazard Weighting
- [ ] Obtain NBRO factor layer data (requires data sharing agreement)
- [ ] Implement Weighted Linear Combination
- [ ] Integrate hazard score into dynamic weight adjustment

### 4.2 Advanced ML Models (LSTM/Transformer)
- [ ] Train moisture/pore pressure forecasting models
- [ ] Implement pre-emptive warnings based on forecasts
- [ ] Evaluate infrastructure needs (SageMaker vs Lambda+ONNX)

### 4.3 Exposure and Vulnerability Integration
- [ ] Integrate Sri Lanka Census population data
- [ ] Integrate road network for evacuation assessment
- [ ] Compute exposure index for alert prioritization

### 4.4 Multilingual Alerts and Dashboard
- [ ] Sinhala/Tamil narrative generation
- [ ] Text-to-speech for voice alerts
- [ ] React-based operator dashboard

### 4.5 Operator Feedback Loops
- [ ] Dashboard for alert review (accept/modify/dismiss)
- [ ] Store feedback annotations
- [ ] Monthly threshold calibration from feedback

### 4.6 LLM Fine-Tuning for Risk Narratives
- [ ] Accumulate 500+ annotated assessments (2-3 monsoon seasons)
- [ ] Create multilingual training corpus
- [ ] Fine-tune for conservative, consistent narratives
- [ ] A/B testing framework
- [ ] Safety checks for overconfident outputs

**Success Criteria:** ≥85% operator approval; ≥90% consistency; zero overconfident predictions

---

## Review Cadence

| Review Type | Timing | Focus Areas |
|-------------|--------|-------------|
| **Weekly Operational** | Every Monday (monsoon) | Alert outcomes, sensor health, uptime |
| **Monthly Technical** | First week of month | Threshold calibration, FP/FN analysis, model drift |
| **Quarterly Retrospective** | Post-monsoon (Jan, Jun) | Season performance, roadmap progress, stakeholder feedback |
| **Annual Strategic** | December | Roadmap update, NBRO collaboration, funding review |

### Quarterly Post-Monsoon Retrospective Agenda
1. Performance review: Compare actual FP/FN rates against targets
2. Threshold recalibration: Adjust based on feedback data
3. Model evaluation: Assess anomaly detector and trend analyzer
4. Roadmap checkpoint: Review progress; reprioritize if needed
5. Stakeholder alignment: Present findings to NBRO
6. Documentation: Update ADRs; archive retrospective report

---

## Ongoing Activities

### Data Governance
- Track metrics in Success Metrics section
- Maintain separate train/validation/test splits
- Document all parameter changes in ADRs
- Tag model versions; maintain rollback capability

### Collaboration
- NBRO: Hazard factor data, historical records, validation
- Disaster Management Centre: Operational requirements
- Department of Meteorology: Weather forecast API access

### Resource Planning
- Target AWS cost: 20-40 AUD/month (+ ~5 AUD for weather API)
- Advanced ML: Budget additional 50-100 AUD/month for SageMaker
- LLM fine-tuning: One-time 100-500 AUD
- Budget alerts at 50%, 80%, 100% of target

---

## Related Documentation

- [Technical Architecture](docs/OpenLEWS-Technical-Architecture-v2.md)
- [Detection Engine README](src/lambdas/detector/README.md)
- [RAG Query README](src/lambdas/rag/README.md)
- [NSDI Data Pipeline README](src/data_ingestion/NSDI/README.md)

---

*This roadmap is a living document. Update task status as work progresses and create GitHub Issues for tracking.*