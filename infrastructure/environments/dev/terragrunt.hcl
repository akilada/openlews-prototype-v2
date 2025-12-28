# Development Environment - Terragrunt Configuration
# File: infrastructure/environments/dev/terragrunt.hcl

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

  dynamodb_table_name = "${local.project_name}-${local.environment}-hazard-zones"
  s3_artifacts_bucket = "${local.project_name}-${local.environment}-lambda-artifacts"

  tags = merge(
    include.root.locals.common_tags,
    {
      Environment = local.environment
    }
  )
}

terraform {
  # IMPORTANT:
  # Copy ONLY infrastructure/modules (not the whole repo),
  #
  # From: infrastructure/environments/dev
  # Base: ../../modules
  # Subdir: all
  source = "../../modules//all"
}

inputs = {
  # Core
  environment  = local.environment
  aws_region   = local.aws_region
  project_name = local.project_name
  name_prefix  = local.name_prefix
  tags         = local.tags

  # Budgets
  monthly_budget_usd = local.env_cfg.locals.monthly_budget_usd
  alert_email        = local.env_cfg.locals.owner_email

  # DynamoDB
  ttl_days                      = local.env_cfg.locals.dynamodb_ttl_days
  enable_point_in_time_recovery = local.env_cfg.locals.enable_point_in_time_recovery

  # S3
  enable_versioning = local.env_cfg.locals.enable_versioning

  # Lambda defaults required by modules/all/variables.tf
  lambda_memory_mb       = local.env_cfg.locals.lambda_memory_mb
  lambda_timeout_seconds = local.env_cfg.locals.lambda_timeout_seconds
  lambda_log_level       = local.env_cfg.locals.lambda_log_level

  # Secrets
  rotation_days = local.env_cfg.locals.rotation_days

  # Cloudwatch
  cloudwatch_log_retention_days = local.env_cfg.locals.cloudwatch_log_retention_days

  # API Gateway
  api_burst_limit     = local.env_cfg.locals.api_burst_limit
  api_quota_limit     = local.env_cfg.locals.api_quota_limit
  api_rate_limit      = local.env_cfg.locals.api_rate_limit
  enable_api_key_auth = local.env_cfg.locals.enable_api_key_auth

  # Lambda RAG Query
  dynamodb_table_name          = local.dynamodb_table_name
  s3_artifacts_bucket          = local.s3_artifacts_bucket
  pinecone_api_key_secret_name = local.env_cfg.locals.pinecone_api_key_secret_name
  pinecone_index_name          = local.env_cfg.locals.pinecone_index_name
  pinecone_namespace           = local.env_cfg.locals.pinecone_namespace
  geohash_index_name           = local.env_cfg.locals.geohash_index_name
  geohash_precision            = local.env_cfg.locals.geohash_precision

  # Lambda Telemetry Ingestor
  enable_ndis_enrichment = local.env_cfg.locals.enable_ndis_enrichment
  enable_eventbridge     = local.env_cfg.locals.enable_eventbridge

  # Lambda Detector
  risk_threshold      = local.env_cfg.locals.risk_threshold
  bedrock_model_id    = local.env_cfg.locals.bedrock_model_id
  schedule_expression = local.env_cfg.locals.schedule_expression

  # Bedrock
  enable_bedrock_logging = local.env_cfg.locals.enable_bedrock_logging
}
