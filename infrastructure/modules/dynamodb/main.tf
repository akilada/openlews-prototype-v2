# DynamoDB Tables Module - Cost Optimized
# On-demand billing, TTL enabled, encryption at rest

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

variable "aws_region" { type = string }

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "ttl_days" {
  description = "Days to retain telemetry data"
  type        = number
  default     = 30
}

variable "enable_point_in_time_recovery" {
  description = "Enable PITR backups (adds cost)"
  type        = bool
  default     = false # Disabled for cost optimization
}

variable "tags" {
  type    = map(string)
  default = {}
}

locals {
  common_tags = {
    Project     = "openlews"
    Environment = var.environment
    ManagedBy   = "terraform"
  }

  dynamodb_table_names_for_kms = [
    "${var.name_prefix}-hazard-zones",
    "${var.name_prefix}-telemetry",
    "${var.name_prefix}-alerts",
  ]
}

data "aws_caller_identity" "current" {}


data "aws_iam_policy_document" "dynamodb_kms_key_policy" {
  statement {
    sid     = "EnableRootPermissions"
    effect  = "Allow"
    actions = ["kms:*"]
    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.current.account_id}:root"]
    }
  }

  # Allow DynamoDB to use the key for encryption/decryption of table keys
  # constrained to account, region, and table names.
  statement {
    sid    = "AllowDynamoDBCryptographicOperations"
    effect = "Allow"
    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:ReEncrypt*",
      "kms:GenerateDataKey*",
      "kms:DescribeKey"
    ]
    resources = ["*"]

    principals {
      type        = "Service"
      identifiers = ["dynamodb.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "kms:CallerAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["dynamodb.${var.aws_region}.amazonaws.com"]
    }

    # Restrict to this account + these table names via DynamoDB encryption context.
    condition {
      test     = "StringEquals"
      variable = "kms:EncryptionContext:aws:dynamodb:subscriberId"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "StringEquals"
      variable = "kms:EncryptionContext:aws:dynamodb:tableName"
      values   = local.dynamodb_table_names_for_kms
    }
  }

  # Allow DynamoDB to create grants for ongoing maintenance tasks.
  statement {
    sid    = "AllowDynamoDBCreateGrant"
    effect = "Allow"
    actions = [
      "kms:CreateGrant",
      "kms:DescribeKey"
    ]
    resources = ["*"]

    principals {
      type        = "Service"
      identifiers = ["dynamodb.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "kms:CallerAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["dynamodb.${var.aws_region}.amazonaws.com"]
    }

    # Only grants for AWS resources
    condition {
      test     = "Bool"
      variable = "kms:GrantIsForAWSResource"
      values   = ["true"]
    }
  }

  statement {
    sid    = "AllowDynamoDBRetireGrant"
    effect = "Allow"
    actions = [
      "kms:RetireGrant",
      "kms:DescribeKey"
    ]
    resources = ["*"]

    principals {
      type        = "Service"
      identifiers = ["dynamodb.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "kms:CallerAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["dynamodb.${var.aws_region}.amazonaws.com"]
    }
  }
}

resource "aws_kms_key" "dynamodb" {
  description             = "KMS key for DynamoDB table encryption"
  deletion_window_in_days = 7
  enable_key_rotation     = true

  policy = data.aws_iam_policy_document.dynamodb_kms_key_policy.json

  tags = {
    Name        = "${var.name_prefix}-dynamodb-key"
    Environment = var.environment
  }
}

resource "aws_kms_alias" "dynamodb" {
  name          = "alias/${var.name_prefix}-dynamodb"
  target_key_id = aws_kms_key.dynamodb.key_id
}

# Hazard Zones Table (NDIS Data)

resource "aws_dynamodb_table" "hazard_zones" {
  name         = "${var.name_prefix}-hazard-zones"
  billing_mode = "PAY_PER_REQUEST"

  # Primary Key: zone_id (hash) + version (range)
  # Allows versioning of hazard zone data
  hash_key  = "zone_id"
  range_key = "version"

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.dynamodb.arn
  }

  # Primary key attributes
  attribute {
    name = "zone_id"
    type = "S"
  }

  attribute {
    name = "version"
    type = "N"
  }

  # GSI attributes
  attribute {
    name = "geohash"
    type = "S"
  }

  attribute {
    name = "level"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "N"
  }

  # GeoHashIndex: For spatial queries by geohash
  global_secondary_index {
    name            = "GeoHashIndex"
    hash_key        = "geohash"
    projection_type = "ALL"
  }

  # LevelIndex: For queries by hazard level with time ordering
  global_secondary_index {
    name            = "LevelIndex"
    hash_key        = "level"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  # Enable TTL for automatic cleanup of old versions
  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }

  tags = merge(local.common_tags, {
    Name        = "${var.name_prefix}-hazard-zones"
    Description = "NDIS landslide hazard zone data for RAG queries"
  })

  lifecycle {
    prevent_destroy = false
  }
}

# Telemetry Table (Sensor Data)

resource "aws_dynamodb_table" "telemetry" {
  name         = "${var.name_prefix}-telemetry"
  billing_mode = "PAY_PER_REQUEST"

  # Primary Key: sensor_id (hash) + timestamp (range)
  hash_key  = "sensor_id"
  range_key = "timestamp"

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.dynamodb.arn
  }

  attribute {
    name = "sensor_id"
    type = "S"
  }

  attribute {
    name = "timestamp"
    type = "N"
  }

  attribute {
    name = "hazard_level"
    type = "S"
  }

  attribute {
    name = "failure_stage"
    type = "S"
  }

  attribute {
    name = "geohash"
    type = "S"
  }

  global_secondary_index {
    name            = "HazardLevelIndex"
    hash_key        = "hazard_level"
    range_key       = "timestamp"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "FailureStageIndex"
    hash_key        = "failure_stage"
    range_key       = "timestamp"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "SpatialIndex"
    hash_key        = "geohash"
    range_key       = "timestamp"
    projection_type = "ALL"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }

  tags = merge(local.common_tags, {
    Name        = "${var.name_prefix}-telemetry"
    Description = "Sensor telemetry time-series data"
  })

  lifecycle {
    prevent_destroy = false
  }
}

# Detection Alerts Table

resource "aws_dynamodb_table" "alerts" {
  name         = "${var.name_prefix}-alerts"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "alert_id"
  range_key    = "created_at"

  server_side_encryption {
    enabled     = true
    kms_key_arn = aws_kms_key.dynamodb.arn
  }

  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }

  attribute {
    name = "alert_id"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "N"
  }

  attribute {
    name = "status"
    type = "S"
  }

  attribute {
    name = "risk_level"
    type = "S"
  }

  global_secondary_index {
    name            = "StatusIndex"
    hash_key        = "status"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "RiskLevelIndex"
    hash_key        = "risk_level"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  tags = {
    Name        = "${var.name_prefix}-alerts"
    Purpose     = "Detection alert records"
    Environment = var.environment
  }
}


# Outputs

output "telemetry_table_name" {
  description = "Name of telemetry DynamoDB table"
  value       = aws_dynamodb_table.telemetry.name
}

output "telemetry_table_arn" {
  description = "ARN of telemetry DynamoDB table"
  value       = aws_dynamodb_table.telemetry.arn
}

output "hazard_zones_table_name" {
  description = "Name of hazard zones DynamoDB table"
  value       = aws_dynamodb_table.hazard_zones.name
}

output "hazard_zones_table_arn" {
  description = "ARN of hazard zones DynamoDB table"
  value       = aws_dynamodb_table.hazard_zones.arn
}

output "alerts_table_name" {
  description = "Name of alerts DynamoDB table"
  value       = aws_dynamodb_table.alerts.name
}

output "alerts_table_arn" {
  description = "ARN of alerts DynamoDB table"
  value       = aws_dynamodb_table.alerts.arn
}

output "kms_key_id" {
  description = "KMS key ID for DynamoDB encryption"
  value       = aws_kms_key.dynamodb.id
}

output "kms_key_arn" {
  description = "KMS key ARN for DynamoDB encryption"
  value       = aws_kms_key.dynamodb.arn
}
