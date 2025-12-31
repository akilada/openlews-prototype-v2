# Development Environment Configuration
# File: infrastructure/environments/dev/env.hcl

locals {
  # AWS Configuration
  aws_region     = "ap-southeast-2"
  aws_account_id = get_env("AWS_ACCOUNT_ID", "")

  # Environment
  environment = "dev"

  # Project naming
  project_name = "openlews"
  name_prefix  = "${local.project_name}-${local.environment}"

  # Cost Limits
  monthly_budget_usd = 15 # Hard limit
  alert_threshold_1  = 50
  alert_threshold_2  = 80
  alert_threshold_3  = 100

  # Resource Configuration
  lambda_memory_mb       = 256
  lambda_timeout_seconds = 60
  lambda_log_level       = "INFO"

  dynamodb_billing_mode = "PAY_PER_REQUEST"
  dynamodb_ttl_days     = 10 # Temporary setting for cost saving and prototype

  enable_point_in_time_recovery = false
  enable_versioning             = false

  # Simulation Settings
  telemetry_interval_minutes = 15
  sensors_count              = 25 # Quincunx grid (5x5)

  # LLM Configuration
  llm_tier1_model = "meta.llama3-3-70b-instruct-v1:0"        # Bulk scanning
  llm_tier2_model = "anthropic.claude-3-haiku-20240307-v1:0" # Complex reasoning

  # Security
  enable_encryption  = true
  cloudtrail_enabled = true

  # Monitoring
  cloudwatch_log_retention_days = 3 # Cost saving and prototype setting
  enable_xray_tracing           = false

  # RAG Query Lambda
  dynamodb_table_name = "${local.project_name}-${local.environment}-hazard-zones"
  s3_artifacts_bucket = "${local.project_name}-${local.environment}-lambda-artifacts"

  # Pinecone Settings
  pinecone_api_key_secret_name = "pinecone/api-key"
  pinecone_index_name          = "lews-geological-knowledge"
  pinecone_namespace           = "openlews"

  # Secrets rotation
  rotation_days = 90

  # Ingestor Lambda

  # DynamoDB Tables
  geohash_index_name = "GeoHashIndex"
  geohash_precision  = 4

  # Table creation
  create_telemetry_table = true

  # Feature flags
  enable_nsdi_enrichment = true
  enable_eventbridge     = true

  # API Gateway Authentication & Rate Limiting
  enable_api_key_auth = true
  api_quota_limit     = 100000
  api_burst_limit     = 100
  api_rate_limit      = 50

  # Lambda Detector
  risk_threshold      = 0.6
  bedrock_model_id    = "anthropic.claude-3-haiku-20240307-v1:0"
  schedule_expression = "rate(15 minutes)"

  # Bedrock
  enable_bedrock_logging = false

  # Notification
  ses_from_email = ""
  ses_to_emails  = [""]
  timezone       = "Asia/Colombo"

  # Tags / ownership
  owner_email = get_env("OWNER_EMAIL", " ")
}
