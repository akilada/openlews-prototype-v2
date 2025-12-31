# Infrastructure

**Terragrunt + OpenTofu Infrastructure as Code for OpenLEWS**

---

## Overview

The infrastructure is managed using Terragrunt for orchestration and OpenTofu (Terraform-compatible) for resource provisioning. The setup follows a modular pattern with environment-specific configurations.

---

## Directory Structure

```
infrastructure/
├── terragrunt.hcl              # Root Terragrunt config (backend, common tags)
├── environments/
│   ├── dev/
│   │   ├── env.hcl             # Dev environment variables
│   │   └── terragrunt.hcl      # Dev Terragrunt config
│   ├── uat/                    # UAT environment (placeholder)
│   └── prod/                   # Production environment (placeholder)
└── modules/
    ├── all/                    # Orchestrator module (calls all sub-modules)
    │   ├── main.tf
    │   └── variables.tf
    ├── budgets/
    │   └── main.tf             # AWS Budgets for cost control
    ├── dynamodb/
    │   └── main.tf             # DynamoDB tables
    ├── s3/
    │   └── main.tf             # S3 buckets
    ├── secrets/
    │   └── main.tf             # Secrets Manager
    ├── location/
    │   └── main.tf             # Amazon Location Service
    ├── iot/                    # IoT Core (placeholder)
    └── lambda/
        ├── detector/
        │   ├── main.tf
        │   ├── bedrock.tf      # Bedrock IAM permissions
        │   ├── variables.tf
        │   ├── outputs.tf
        │   └── build.sh        # Lambda packaging script
        ├── rag_query/
        │   ├── main.tf
        │   └── build.sh
        └── telemetry_ingestor/
            ├── main.tf
            ├── api_gateway.tf  # API Gateway configuration
            └── build.sh
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Terragrunt                                     │
│                                                                             │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                    environments/dev/terragrunt.hcl                     │ │
│  │  - Includes root terragrunt.hcl                                        │ │
│  │  - Reads env.hcl for environment-specific values                       │ │
│  │  - Sources modules/all                                                 │ │
│  │  - Passes inputs to modules                                            │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                    ↓                                        │
│  ┌────────────────────────────────────────────────────────────────────────┐ │
│  │                         modules/all/main.tf                            │ │
│  │  - Orchestrates all sub-modules                                        │ │
│  │  - Manages module dependencies                                         │ │
│  └────────────────────────────────────────────────────────────────────────┘ │
│                                    ↓                                        │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │
│  │ budgets  │ │ dynamodb │ │    s3    │ │ secrets  │ │ location │           │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘           │
│                     ↓                                      ↓                │
│  ┌─────────────────────────────────────────────────────────────────────────┐│
│  │                         lambda/ modules                                 ││
│  │  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────┐  ││
│  │  │   rag_query     │  │telemetry_ingest │  │       detector          │  ││
│  │  │                 │  │ + api_gateway   │  │ + bedrock permissions   │  ││
│  │  └─────────────────┘  └─────────────────┘  └─────────────────────────┘  ││
│  └─────────────────────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Modules

### `modules/all` - Orchestrator

The main entry point that composes all infrastructure modules:

```hcl
# modules/all/main.tf

module "budgets" {
  source = "../budgets"
  # ...
}

module "dynamodb" {
  source = "../dynamodb"
  # ...
}

module "s3" {
  source = "../s3"
  # ...
}

module "secrets" {
  source = "../secrets"
  # ...
}

module "location" {
  source = "../location"
  # ...
}

module "lambda_rag_query" {
  source = "../lambda/rag_query"
  dynamodb_kms_arn = module.dynamodb.kms_key_arn
  depends_on = [module.dynamodb]
}

module "lambda_telemetry_ingestor" {
  source = "../lambda/telemetry_ingestor"
  telemetry_table_name = module.dynamodb.telemetry_table_name
  hazard_zones_table_name = module.dynamodb.hazard_zones_table_name
  depends_on = [module.dynamodb]
}

module "lambda_detector" {
  source = "../lambda/detector"
  telemetry_table_name = module.dynamodb.telemetry_table_name
  alerts_table_name = module.dynamodb.alerts_table_name
  rag_lambda_arn = module.lambda_rag_query.lambda_function_arn
  place_index_name = module.location.place_index_name
  depends_on = [module.dynamodb, module.lambda_telemetry_ingestor]
}
```

### `modules/budgets`

AWS Budgets for cost control:

| Resource | Purpose |
|----------|---------|
| aws_budgets_budget | Monthly cost limit with email alerts |

### `modules/dynamodb`

DynamoDB tables for data storage:

| Table | Purpose | Keys |
|-------|---------|------|
| Telemetry | Sensor readings | PK: sensor_id, SK: timestamp |
| Hazard Zones | NSDI zone data | PK: zone_id, GSI: GeoHashIndex |
| Alerts | Detection alerts | PK: alert_id, SK: created_at |

### `modules/s3`

S3 buckets:

| Bucket | Purpose |
|--------|---------|
| Lambda Artifacts | Deployment packages |

### `modules/secrets`

Secrets Manager:

| Secret | Purpose |
|--------|---------|
| pinecone/api-key | Pinecone API credentials |

### `modules/location`

Amazon Location Service:

| Resource | Purpose |
|----------|---------|
| Place Index | Reverse geocoding for alerts |

### `modules/lambda/rag_query`

RAG Query Lambda:

| Resource | Purpose |
|----------|---------|
| Lambda Function | Geospatial hazard zone lookup |
| IAM Role | DynamoDB, Secrets Manager access |
| CloudWatch Logs | Function logging |

### `modules/lambda/telemetry_ingestor`

Telemetry Ingestor Lambda + API Gateway:

| Resource | Purpose |
|----------|---------|
| Lambda Function | Telemetry ingestion |
| API Gateway REST API | HTTP endpoint |
| API Key + Usage Plan | Rate limiting & authentication |
| IAM Role | DynamoDB, EventBridge access |

### `modules/lambda/detector`

Detection Engine Lambda:

| Resource | Purpose |
|----------|---------|
| Lambda Function | Risk analysis |
| EventBridge Rule | Scheduled execution |
| SNS Topic | Alert notifications |
| IAM Role | DynamoDB, Bedrock, Lambda invoke, Location Service |
| Bedrock Permissions | Claude model access |

---

## Environment Configuration

### `environments/dev/env.hcl`

Development environment settings:

```hcl
locals {
  # AWS Configuration
  aws_region     = "ap-southeast-2"
  environment    = "dev"
  project_name   = "openlews"
  name_prefix    = "${local.project_name}-${local.environment}"

  # Cost Limits
  monthly_budget_usd = 15

  # Lambda Configuration
  lambda_memory_mb       = 256
  lambda_timeout_seconds = 60
  lambda_log_level       = "INFO"

  # DynamoDB
  dynamodb_ttl_days              = 10
  enable_point_in_time_recovery  = false

  # S3
  enable_versioning = false

  # LLM Configuration
  bedrock_model_id = "anthropic.claude-3-haiku-20240307-v1:0"

  # Monitoring
  cloudwatch_log_retention_days = 3

  # RAG Query Lambda
  dynamodb_table_name = "${local.project_name}-${local.environment}-hazard-zones"
  s3_artifacts_bucket = "${local.project_name}-${local.environment}-lambda-artifacts"

  # Pinecone Settings
  pinecone_api_key_secret_name = "pinecone/api-key"
  pinecone_index_name          = "lews-geological-knowledge"
  pinecone_namespace           = "openlews"

  # GeoHash Index
  geohash_index_name = "GeoHashIndex"
  geohash_precision  = 4

  # Feature Flags
  enable_nsdi_enrichment = true
  enable_eventbridge     = true

  # API Gateway
  enable_api_key_auth = true
  api_quota_limit     = 100000
  api_burst_limit     = 100
  api_rate_limit      = 50

  # Detector
  risk_threshold      = 0.6
  schedule_expression = "rate(15 minutes)"

  # Secrets
  rotation_days = 90
}
```

### `environments/dev/terragrunt.hcl`

Terragrunt configuration for dev:

```hcl
include "root" {
  path   = find_in_parent_folders("terragrunt.hcl")
  expose = true
}

locals {
  env_cfg     = read_terragrunt_config("${get_terragrunt_dir()}/env.hcl")
  environment = local.env_cfg.locals.environment
  aws_region  = local.env_cfg.locals.aws_region
  project_name = include.root.locals.project_name
  name_prefix  = "${local.project_name}-${local.environment}"
}

terraform {
  source = "../../modules//all"
}

inputs = {
  # Core
  environment  = local.environment
  aws_region   = local.aws_region
  project_name = local.project_name
  name_prefix  = local.name_prefix

  # All other inputs from env.hcl...
}
```

---

## Variables Reference

### Core Variables

| Variable | Type | Description |
|----------|------|-------------|
| `environment` | string | Environment name (dev, uat, prod) |
| `aws_region` | string | AWS region |
| `project_name` | string | Project identifier |
| `name_prefix` | string | Resource naming prefix |

### Budget Variables

| Variable | Type | Description |
|----------|------|-------------|
| `monthly_budget_usd` | number | Monthly budget limit |
| `alert_email` | string | Email for budget alerts |

### DynamoDB Variables

| Variable | Type | Description |
|----------|------|-------------|
| `ttl_days` | number | TTL for telemetry records |
| `enable_point_in_time_recovery` | bool | Enable PITR backups |

### Lambda Variables

| Variable | Type | Description |
|----------|------|-------------|
| `lambda_memory_mb` | number | Lambda memory allocation |
| `lambda_timeout_seconds` | number | Lambda timeout |
| `lambda_log_level` | string | Log level (DEBUG, INFO, etc.) |
| `cloudwatch_log_retention_days` | number | Log retention period |

### API Gateway Variables

| Variable | Type | Description |
|----------|------|-------------|
| `enable_api_key_auth` | bool | Require API key |
| `api_quota_limit` | number | Monthly request quota |
| `api_burst_limit` | number | Burst limit |
| `api_rate_limit` | number | Requests per second |

### RAG Query Variables

| Variable | Type | Description |
|----------|------|-------------|
| `dynamodb_table_name` | string | Hazard zones table name |
| `s3_artifacts_bucket` | string | Lambda artifacts bucket |
| `pinecone_api_key_secret_name` | string | Secrets Manager secret name |
| `pinecone_index_name` | string | Pinecone index |
| `pinecone_namespace` | string | Pinecone namespace |
| `geohash_index_name` | string | DynamoDB GSI name |
| `geohash_precision` | number | Geohash precision (4) |

### Telemetry Ingestor Variables

| Variable | Type | Description |
|----------|------|-------------|
| `enable_nsdi_enrichment` | bool | Enable hazard zone enrichment |
| `enable_eventbridge` | bool | Publish high-risk events |

### Detector Variables

| Variable | Type | Description |
|----------|------|-------------|
| `risk_threshold` | number | Alert threshold (0.6) |
| `bedrock_model_id` | string | Claude model ID |
| `schedule_expression` | string | EventBridge schedule |
| `enable_bedrock_logging` | bool | Enable Bedrock logging |

---

## Deployment

### Prerequisites

```bash
# Install OpenTofu
brew install opentofu

# Install Terragrunt
brew install terragrunt

# Configure AWS credentials
aws configure --profile openlews-dev
export AWS_PROFILE=openlews-dev
```

### Deploy Development Environment

```bash
cd infrastructure/environments/dev

# Initialize
terragrunt init

# Plan
terragrunt plan

# Apply
terragrunt apply
```

### Deploy All Environments

```bash
cd infrastructure/environments

# Run across all environments
terragrunt run-all plan
terragrunt run-all apply
```

### Destroy

```bash
cd infrastructure/environments/dev
terragrunt destroy
```

---

## Module Dependencies

```
budgets ───────────────────────────────────────────────┐
                                                       │
dynamodb ──────────────────────────────────────────────┼──→ outputs
    │                                                  │
    ├──→ lambda_rag_query ─────────────────────────────┤
    │         │                                        │
    ├──→ lambda_telemetry_ingestor ────────────────────┤
    │         │                                        │
    └──→ lambda_detector ──────────────────────────────┤
              │                                        │
              ├── depends_on: dynamodb                 │
              ├── depends_on: lambda_telemetry_ingestor│
              └── uses: rag_lambda_arn                 │
                                                       │
s3 ────────────────────────────────────────────────────┤
                                                       │
secrets ───────────────────────────────────────────────┤
                                                       │
location ──────────────────────────────────────────────┘
    │
    └──→ place_index_name, place_index_arn → lambda_detector
```

---

## Resource Naming Convention

Resources follow the pattern: `{project_name}-{environment}-{resource_type}`

Examples:
- `openlews-dev-telemetry` (DynamoDB table)
- `openlews-dev-hazard-zones` (DynamoDB table)
- `openlews-dev-alerts` (DynamoDB table)
- `openlews-dev-lambda-artifacts` (S3 bucket)
- `openlews-dev-detector` (Lambda function)

---

## Cost Optimization (Dev Environment)

| Setting | Value | Reason |
|---------|-------|--------|
| DynamoDB billing | PAY_PER_REQUEST | Low traffic |
| TTL days | 10 | Reduce storage |
| Log retention | 3 days | Reduce CloudWatch costs |
| PITR | Disabled | Not needed for prototype |
| S3 versioning | Disabled | Not needed for prototype |
| Monthly budget | $15 | Hard limit with alerts |

---

## Lambda Build Scripts

Each Lambda module includes a `build.sh` script for packaging:

```bash
# Example: modules/lambda/detector/build.sh
#!/bin/bash
set -e

cd ../../../src/lambdas/detector
pip install -r requirements.txt -t package/
cp -r *.py core/ clients/ utils/ package/
cd package && zip -r ../detector.zip .
```

---

## Outputs

Key outputs from the infrastructure:

| Output | Source Module | Description |
|--------|---------------|-------------|
| `telemetry_table_name` | dynamodb | Telemetry table name |
| `hazard_zones_table_name` | dynamodb | Hazard zones table name |
| `alerts_table_name` | dynamodb | Alerts table name |
| `kms_key_arn` | dynamodb | KMS key for encryption |
| `lambda_function_arn` | lambda_rag_query | RAG Lambda ARN |
| `api_endpoint` | lambda_telemetry_ingestor | API Gateway URL |
| `place_index_name` | location | Location Service index |

---

## Troubleshooting

### State Lock Issues

```bash
# If state is locked
terragrunt force-unlock <LOCK_ID>
```

### Module Not Found

```bash
# Clear cache and reinitialize
rm -rf .terragrunt-cache
terragrunt init
```

### Dependency Errors

Check `depends_on` blocks in `modules/all/main.tf` to ensure proper ordering.

---

## Related Components

- [Detector Lambda](../src/lambdas/detector/README.md)
- [RAG Query Lambda](../src/lambdas/rag/README.md)
- [Telemetry Ingestor Lambda](../src/lambdas/telemetry_ingestor/README.md)
- [NSDI Data Ingestion](../src/data_ingestion/NSDI/README.md)