# OpenLEWS Detector Lambda - Complete Installation Guide

## 📦 Package Contents

You've received: **openlews-detector-package.tar.gz** (30KB)

This package contains the complete LLM Intelligence Layer for OpenLEWS.

---

## 🚀 Quick Start (30 Minutes)

### Prerequisites Checklist

Before installation, verify:

- [x] **Existing Infrastructure**:
  - DynamoDB telemetry table (e.g., `openlews-dev-telemetry`)
  - RAG Query Lambda deployed
  - Simulator generating telemetry data

- [x] **AWS Access**:
  - AWS CLI configured
  - Bedrock access enabled (Claude 3.5 Sonnet)
  - IAM permissions for Lambda, DynamoDB, SNS, EventBridge

- [x] **Local Environment**:
  - Python 3.11
  - Terraform/OpenTofu 1.6+
  - bash shell

---

## 📂 Step 1: Extract Package

```bash
# Navigate to your repository root
cd ~/openlews-prototype

# Extract package
tar -xzf openlews-detector-package.tar.gz

# Verify extraction
ls -la openlews-detector-package/
```

Expected output:
```
README.md
MANIFEST.md
src/
infrastructure/
tests/
docs/
```

### Copy to Repository Structure

```bash
# Lambda code
cp -r openlews-detector-package/src/lambdas/detector src/lambdas/

# Terraform module
cp -r openlews-detector-package/infrastructure/modules/lambda/detector infrastructure/modules/lambda/

# Tests
cp -r openlews-detector-package/tests/detector tests/

# Documentation
cp openlews-detector-package/README.md docs/DETECTOR_README.md
cp openlews-detector-package/docs/DEPLOYMENT.md docs/DETECTOR_DEPLOYMENT.md
```

---

## 🔨 Step 2: Build Lambda Package

```bash
cd src/lambdas/detector

# Make build script executable
chmod +x build.sh

# Build package
./build.sh
```

Expected output:
```
Building Detector Lambda package...
Installing dependencies...
Copying Lambda code...
Creating deployment package...
✓ Package created: lambda_package.zip
✓ Package size: 2.1M
✓ Build complete!
```

**Troubleshooting**:
- If pip install fails, create virtual environment first:
  ```bash
  python3.11 -m venv venv
  source venv/bin/activate
  pip install --upgrade pip
  ./build.sh
  ```

---

## ☁️ Step 3: Deploy Infrastructure

### Get Required ARNs

First, get the ARNs you'll need:

```bash
# RAG Lambda ARN
aws lambda get-function \
  --function-name openlews-dev-rag-query \
  --query 'Configuration.FunctionArn' \
  --output text

# Save this ARN for next step
```

### Option A: Standalone Terraform Deployment

```bash
cd infrastructure/modules/lambda/detector

# Initialize
terraform init

# Create variables file
cat > terraform.tfvars <<EOF
project_name = "openlews"
environment = "dev"
region = "ap-southeast-2"  # Or your region
lambda_package_path = "../../../src/lambdas/detector/lambda_package.zip"
telemetry_table_name = "openlews-dev-telemetry"
rag_lambda_arn = "arn:aws:lambda:REGION:ACCOUNT:function:openlews-dev-rag-query"
alert_email = "your@email.com"  # For SNS notifications
risk_threshold = 0.6
schedule_expression = "rate(15 minutes)"
EOF

# Plan
terraform plan

# Apply
terraform apply
```

### Option B: Terragrunt Integration (Recommended)

Create `infrastructure/environments/dev/detector/terragrunt.hcl`:

```hcl
include "root" {
  path = find_in_parent_folders()
}

include "env" {
  path = find_in_parent_folders("env.hcl")
}

terraform {
  source = "${get_repo_root()}//infrastructure/modules/lambda/detector"
}

dependency "telemetry" {
  config_path = "../dynamodb"
  
  mock_outputs = {
    telemetry_table_name = "openlews-dev-telemetry"
  }
}

dependency "rag" {
  config_path = "../lambda/rag_query"
  
  mock_outputs = {
    lambda_arn = "arn:aws:lambda:ap-southeast-2:123456789012:function:mock-rag"
  }
}

inputs = {
  lambda_package_path = "${get_repo_root()}/src/lambdas/detector/lambda_package.zip"
  
  telemetry_table_name = dependency.telemetry.outputs.telemetry_table_name
  rag_lambda_arn = dependency.rag.outputs.lambda_arn
  
  alert_email = "your@email.com"
  risk_threshold = 0.6
  schedule_expression = "rate(15 minutes)"
  log_level = "INFO"
  
  tags = {
    Component = "Detector"
    ManagedBy = "Terragrunt"
  }
}
```

Then deploy:

```bash
cd infrastructure/environments/dev/detector
terragrunt apply
```

---

## ✅ Step 4: Verify Deployment

### Check Lambda Function

```bash
aws lambda get-function \
  --function-name openlews-dev-detector \
  --query 'Configuration.[FunctionName,Runtime,Timeout,MemorySize]' \
  --output table
```

Expected:
```
---------------------------------
|         GetFunction           |
+-------------------------------+
|  openlews-dev-detector        |
|  python3.11                   |
|  300                          |
|  512                          |
+-------------------------------+
```

### Check EventBridge Schedule

```bash
aws events describe-rule \
  --name openlews-dev-detector-schedule \
  --query '[Name,ScheduleExpression,State]' \
  --output table
```

Expected: `rate(15 minutes)` and `ENABLED`

### Check DynamoDB Alerts Table

```bash
aws dynamodb describe-table \
  --table-name openlews-dev-alerts \
  --query 'Table.[TableName,TableStatus,BillingModeSummary.BillingMode]' \
  --output table
```

### Check SNS Topic

```bash
aws sns list-subscriptions-by-topic \
  --topic-arn $(aws sns list-topics --query 'Topics[?contains(TopicArn, `openlews-dev-alerts`)].TopicArn' --output text)
```

**Important**: Check your email and confirm the SNS subscription!

---

## 🧪 Step 5: Test Detection

### Manual Test Invocation

```bash
# Invoke detector manually
aws lambda invoke \
  --function-name openlews-dev-detector \
  --payload '{}' \
  --log-type Tail \
  response.json

# Check response
cat response.json | jq '.'
```

Expected output:
```json
{
  "statusCode": 200,
  "body": "{\"status\":\"success\",\"sensors_analyzed\":25,\"clusters_detected\":0,\"alerts_created\":0,\"execution_time\":2.3}"
}
```

### Check CloudWatch Logs

```bash
# Tail logs (wait for next scheduled run or use manual invoke)
aws logs tail /aws/lambda/openlews-dev-detector --follow --format short
```

Look for:
- "Starting detector analysis"
- "Fetching telemetry for last 24 hours"
- "Analysis complete"
- Risk scores for individual sensors

---

## 🧪 Step 6: Run Tests

### Unit Tests

```bash
cd tests/detector/unit

# Install pytest
pip install pytest

# Run tests
pytest test_fusion_algorithm.py -v
```

Expected output:
```
test_haversine_distance PASSED
test_spatial_correlation_high_agreement PASSED
test_spatial_correlation_isolated_anomaly PASSED
test_composite_risk_boost PASSED
test_composite_risk_reduction PASSED
test_cluster_detection_aranayake_pattern PASSED
test_no_cluster_for_isolated_sensors PASSED

========== 7 passed in 0.15s ==========
```

### Scenario Replays

**Aranayake 2016** (catastrophic failure):
```bash
cd tests/detector/scenarios
python test_aranayake_replay.py
```

Expected:
```
✅ SUCCESS: Red alert issued 10 hours before failure
   (Requirement: 6+ hours)
```

**Ditwah 2025** (slow creep):
```bash
python test_ditwah_replay.py
```

Expected:
```
✅ SUCCESS: Proper escalation path verified
   Yellow (Day 4) → Orange (Day 7) → Red (Day 9)
   Total warning period: 5 days
```

---

## 🔗 Step 7: Integration with Simulator

The detector automatically reads from the telemetry table that your simulator writes to. No code changes needed!

### Verify Data Flow

```bash
# Check recent telemetry
aws dynamodb scan \
  --table-name openlews-dev-telemetry \
  --max-items 5 \
  --query 'Items[*].[sensor_id.S,timestamp.N,moisture_percent.N]' \
  --output table

# Wait 15 minutes for next scheduled detection run

# Check if alerts were created
aws dynamodb scan \
  --table-name openlews-dev-alerts \
  --max-items 5 \
  --query 'Items[*].[alert_id.S,risk_level.S,created_at.N]' \
  --output table
```

---

## 📊 Step 8: Monitoring Setup

### Create CloudWatch Dashboard

```bash
# Use AWS Console or create via CLI
aws cloudwatch put-dashboard \
  --dashboard-name OpenLEWS-Detector \
  --dashboard-body file://dashboard.json
```

Where `dashboard.json` contains:
```json
{
  "widgets": [
    {
      "type": "metric",
      "properties": {
        "metrics": [
          ["AWS/Lambda", "Invocations", {"stat": "Sum", "label": "Detections"}],
          [".", "Errors", {"stat": "Sum", "label": "Errors"}],
          [".", "Duration", {"stat": "Average", "label": "Duration (ms)"}]
        ],
        "period": 300,
        "stat": "Sum",
        "region": "ap-southeast-2",
        "title": "Detector Lambda Metrics",
        "yAxis": {"left": {"min": 0}}
      }
    }
  ]
}
```

### Set Budget Alert

```bash
aws budgets create-budget \
  --account-id $(aws sts get-caller-identity --query Account --output text) \
  --budget file://budget.json

# budget.json
{
  "BudgetName": "OpenLEWS-Detector-Budget",
  "BudgetLimit": {"Amount": "10", "Unit": "USD"},
  "TimeUnit": "MONTHLY",
  "BudgetType": "COST",
  "CostFilters": {
    "TagKeyValue": ["user:Project$openlews"]
  }
}
```

---

## 🎯 Configuration Tuning

### Adjust Risk Threshold

If you're getting too many/few alerts:

```bash
# Update Lambda environment variable
aws lambda update-function-configuration \
  --function-name openlews-dev-detector \
  --environment "Variables={RISK_THRESHOLD=0.7}"  # Increase for fewer alerts
```

### Change Detection Frequency

```bash
# Update EventBridge rule
aws events put-rule \
  --name openlews-dev-detector-schedule \
  --schedule-expression "rate(5 minutes)"  # Faster detection
```

---

## 🐛 Troubleshooting

### No Alerts Generated

**Check**:
1. Telemetry data exists:
   ```bash
   aws dynamodb get-item \
     --table-name openlews-dev-telemetry \
     --key '{"sensor_id":{"S":"SENSOR_01"},"timestamp":{"N":"'$(date +%s)'"}}'
   ```

2. Risk scores in logs:
   ```bash
   aws logs filter-pattern /aws/lambda/openlews-dev-detector \
     --filter-pattern "Risk calculated" \
     --start-time -1h
   ```

3. Check risk threshold (maybe too high)

### Lambda Timeout

**Solution**: Increase timeout in Terraform:
```hcl
timeout = 600  # 10 minutes
```

### Bedrock Errors

**Check**:
```bash
# Verify Bedrock access
aws bedrock list-foundation-models \
  --query 'modelSummaries[?contains(modelId, `claude-3-haiku-20240307`)].modelId'
```

If empty, request Bedrock access in AWS Console.

---

## 📈 Cost Monitoring

Expected monthly costs:

| Component | Dev | Prod |
|-----------|-----|------|
| Lambda | $1 | $3 |
| Bedrock | $2 | $6 |
| DynamoDB | $0.50 | $1 |
| SNS | $0.02 | $0.05 |
| **Total** | **$3.52** | **$10.05** |

Monitor actual costs:
```bash
aws ce get-cost-and-usage \
  --time-period Start=2025-12-01,End=2025-12-31 \
  --granularity MONTHLY \
  --metrics UnblendedCost \
  --filter file://cost-filter.json
```

---

## 🎓 Next Steps

1. **Review Alerts**: Check SNS emails for test alerts
2. **Tune Thresholds**: Adjust based on your risk tolerance
3. **Add Monitoring**: Set up CloudWatch Alarms
4. **Production Deployment**: Repeat for prod environment
5. **Integrate Notifications**: Connect SNS to Slack, PagerDuty, etc.

---

## 📚 Documentation

- **README.md**: Package overview
- **docs/DETECTOR_DEPLOYMENT.md**: Detailed deployment guide
- **MANIFEST.md**: File inventory
- **Inline code comments**: Implementation details

---

## 🆘 Support

If you encounter issues:

1. Check CloudWatch Logs: `/aws/lambda/openlews-dev-detector`
2. Review Terraform state: `terraform show`
3. Run tests: `pytest tests/detector/ -v`
4. Contact: team@openlews.org

---

## ✨ Success Criteria

You're done when:

- [x] Lambda function deployed
- [x] EventBridge schedule active
- [x] DynamoDB Alerts table created
- [x] SNS subscription confirmed
- [x] Manual invoke succeeds
- [x] Unit tests pass
- [x] Scenario replays succeed
- [x] CloudWatch logs show detections
- [x] Monitoring dashboard created

**Congratulations! Your LLM Intelligence Layer is operational.** 🎉