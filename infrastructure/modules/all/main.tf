terraform {
  required_version = ">= 1.6.0"
}

module "budgets" {
  source = "../budgets"

  environment        = var.environment
  aws_region         = var.aws_region
  name_prefix        = var.name_prefix
  monthly_budget_usd = var.monthly_budget_usd
  alert_email        = var.alert_email
  tags               = var.tags
}

module "dynamodb" {
  source = "../dynamodb"

  environment                   = var.environment
  aws_region                    = var.aws_region
  name_prefix                   = var.name_prefix
  ttl_days                      = var.ttl_days
  enable_point_in_time_recovery = var.enable_point_in_time_recovery

  tags = var.tags
}

module "s3" {
  source = "../s3"

  environment       = var.environment
  aws_region        = var.aws_region
  name_prefix       = var.name_prefix
  enable_versioning = var.enable_versioning
  tags              = var.tags
}

module "secrets" {
  source = "../secrets"

  environment   = var.environment
  aws_region    = var.aws_region
  name_prefix   = var.name_prefix
  rotation_days = var.rotation_days
  tags          = var.tags
}

module "location" {
  source       = "../location"
  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region
  tags         = var.tags
}

module "lambda_rag_query" {
  source = "../lambda/rag_query"

  environment                  = var.environment
  project_name                 = var.project_name
  dynamodb_table_name          = var.dynamodb_table_name
  dynamodb_kms_arn             = module.dynamodb.kms_key_arn
  s3_artifacts_bucket          = var.s3_artifacts_bucket
  pinecone_api_key_secret_name = var.pinecone_api_key_secret_name
  pinecone_index_name          = var.pinecone_index_name
  pinecone_namespace           = var.pinecone_namespace
  geohash_index_name           = var.geohash_index_name
  geohash_precision            = var.geohash_precision
  tags                         = var.tags

  depends_on = [
    module.dynamodb
  ]
}

module "lambda_telemetry_ingestor" {
  source = "../lambda/telemetry_ingestor"

  environment                   = var.environment
  project_name                  = var.project_name
  telemetry_table_name          = module.dynamodb.telemetry_table_name
  hazard_zones_table_name       = module.dynamodb.hazard_zones_table_name
  hazard_zones_table_arn        = module.dynamodb.hazard_zones_table_arn
  dynamodb_kms_arn              = module.dynamodb.kms_key_arn
  enable_nsdi_enrichment        = var.enable_nsdi_enrichment
  enable_eventbridge            = var.enable_eventbridge
  cloudwatch_log_retention_days = var.cloudwatch_log_retention_days
  lambda_timeout_seconds        = var.lambda_timeout_seconds
  lambda_memory_mb              = var.lambda_memory_mb
  api_burst_limit               = var.api_burst_limit
  api_quota_limit               = var.api_quota_limit
  api_rate_limit                = var.api_rate_limit
  enable_api_key_auth           = var.enable_api_key_auth

  tags = var.tags

  depends_on = [
    module.dynamodb
  ]
}

module "lambda_detector" {
  source = "../lambda/detector"

  environment                   = var.environment
  project_name                  = var.project_name
  aws_region                    = var.aws_region
  telemetry_table_name          = module.dynamodb.telemetry_table_name
  alerts_table_name             = module.dynamodb.alerts_table_name
  alerts_table_arn              = module.dynamodb.alerts_table_arn
  dynamodb_kms_arn              = module.dynamodb.kms_key_arn
  rag_lambda_arn                = module.lambda_rag_query.lambda_function_arn
  risk_threshold                = var.risk_threshold
  bedrock_model_id              = var.bedrock_model_id
  schedule_expression           = var.schedule_expression
  cloudwatch_log_retention_days = var.cloudwatch_log_retention_days
  lambda_log_level              = var.lambda_log_level
  enable_point_in_time_recovery = var.enable_point_in_time_recovery
  alert_email                   = var.alert_email
  enable_bedrock_logging        = var.enable_bedrock_logging
  place_index_name              = module.location.place_index_name
  place_index_arn               = module.location.place_index_arn

  tags = var.tags

  depends_on = [
    module.dynamodb,
    module.lambda_telemetry_ingestor
  ]
}

module "alerts_emailer" {
  source = "../notifications"

  project_name = var.project_name
  environment  = var.environment
  region       = var.aws_region

  sns_topic_arn  = module.lambda_detector.sns_topic_arn
  ses_from_email = var.ses_from_email
  ses_to_emails  = var.ses_to_emails
  timezone       = var.timezone

  tags = var.tags
}