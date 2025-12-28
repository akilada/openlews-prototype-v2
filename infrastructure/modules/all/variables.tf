variable "environment" { type = string }
variable "aws_region"  { type = string }
variable "name_prefix" { type = string }
variable "project_name" { type = string }

variable "tags" {
  type    = map(string)
  default = {}
}

# Budgets
variable "monthly_budget_usd" { type = number }
variable "alert_email"        { type = string }

# DynamoDB
variable "ttl_days"                      { type = number }
variable "enable_point_in_time_recovery" { type = bool }

# S3
variable "enable_versioning" { type = bool }

# Lambda
variable "lambda_memory_mb"     { type = number }
variable "lambda_timeout_seconds" { type = number }
variable "lambda_log_level" { type = string }


# Secrets
variable "rotation_days" { type = number }

# API GATEWAY
variable "api_burst_limit" { type = number }
variable "api_quota_limit" { type = number }
variable "api_rate_limit" { type = number }
variable "enable_api_key_auth" { type = bool }

# CloudWathc
variable "cloudwatch_log_retention_days" { type = number }

# Lambda RAG Query
variable "dynamodb_table_name" { type = string }
variable "s3_artifacts_bucket" { type = string }
variable "pinecone_api_key_secret_name" { type = string }
variable "pinecone_index_name" { type = string }
variable "pinecone_namespace" { type = string }
variable "geohash_index_name" { type = string }
variable "geohash_precision" { type = number }

# Lambda Telemetry Ingestor
variable "enable_ndis_enrichment" { type = bool }
variable "enable_eventbridge" { type = bool }

# Lambda Detector
variable "risk_threshold" { type = number }
variable "bedrock_model_id" { type = string }
variable "schedule_expression" { type = string }
# variable "place_index_name" { type = string }

# Bedrock
variable "enable_bedrock_logging" { type = bool }
