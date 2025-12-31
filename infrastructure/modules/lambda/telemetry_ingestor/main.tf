# OpenLEWS Ingestor Lambda Module
# Deploys Lambda function for ingesting sensor telemetry

terraform {
  required_version = ">= 1.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
  }
}

# Variables
variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
}

variable "project_name" {
  description = "Project name prefix"
  type        = string
  default     = "openlews"
}

variable "telemetry_table_name" {
  description = "DynamoDB table name for telemetry data"
  type        = string
}

variable "hazard_zones_table_name" {
  description = "DynamoDB table name for hazard zones (NSDI data)"
  type        = string
}

variable "hazard_zones_table_arn" {
  description = "ARN of hazard zones DynamoDB table"
  type        = string
}

variable "geohash_index_name" {
  description = "Name of geohash GSI on hazard zones table"
  type        = string
  default     = "GeoHashIndex"
}

variable "dynamodb_kms_arn" {
  description = "ARN of DynamoDb KMS key"
  type        = string
}

variable "enable_nsdi_enrichment" {
  description = "Enable NSDI enrichment feature"
  type        = bool
  default     = true
}

variable "enable_eventbridge" {
  description = "Enable EventBridge high-risk event publishing"
  type        = bool
  default     = true
}

variable "cloudwatch_log_retention_days" {
  description = "CloudWatch Logs retention period"
  type        = number
  default     = 7
}

variable "lambda_timeout_seconds" {
  description = "Lambda timeout in seconds"
  type        = number
  default     = 30
}

variable "lambda_memory_mb" {
  description = "Lambda memory in MB"
  type        = number
  default     = 512
}

variable "enable_api_key_auth" {
  description = "Ingestor API Gateway Key"
  type        = bool
  default     = true
}

variable "api_quota_limit" {
  description = "Ingestor API Gateway Quota Limit"
  type        = number
  default     = 100000
}

variable "api_burst_limit" {
  description = "Ingestor API Gateway Burst Limit"
  type        = number
  default     = 100
}

variable "api_rate_limit" {
  description = "Ingestor API Gateway Rate Limit"
  type        = number
  default     = 50
}

variable "tags" {
  description = "Resource tags"
  type        = map(string)
  default     = {}
}

# Local variables
locals {
  function_name = "${var.project_name}-${var.environment}-ingestor"

  common_tags = merge(
    var.tags,
    {
      Environment = var.environment
      ManagedBy   = "Terraform"
      Component   = "Ingestor"
    }
  )
}

# CloudWatch Log Group
resource "aws_cloudwatch_log_group" "lambda_logs" {
  name              = "/aws/lambda/${local.function_name}"
  retention_in_days = var.cloudwatch_log_retention_days

  tags = local.common_tags
}

# IAM Role for Lambda
resource "aws_iam_role" "lambda_role" {
  name = "${local.function_name}-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = local.common_tags
}

# IAM Policy for Lambda
resource "aws_iam_role_policy" "lambda_policy" {
  name = "${local.function_name}-policy"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # CloudWatch Logs
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = [
          aws_cloudwatch_log_group.lambda_logs.arn,
          "${aws_cloudwatch_log_group.lambda_logs.arn}:log-stream:*"
        ]
      },
      # DynamoDB - Write to Telemetry Table
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem",
          "dynamodb:BatchWriteItem"
        ]
        Resource = "arn:aws:dynamodb:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:table/${var.telemetry_table_name}"
      },
      # DynamoDB - Read from Hazard Zones Table (NSDI enrichment)
      {
        Effect = "Allow"
        Action = [
          "dynamodb:Query",
          "dynamodb:GetItem"
        ]
        Resource = [
          var.hazard_zones_table_arn,
          "${var.hazard_zones_table_arn}/index/${var.geohash_index_name}"
        ]
      },
      # DynamoDB - KMS
      {
        Effect = "Allow"
        Action = [
          "kms:Decrypt",
          "kms:Encrypt",
          "kms:GenerateDataKey",
          "kms:DescribeKey"
        ]
        Resource = "${var.dynamodb_kms_arn}"
      },
      # EventBridge - Publish high-risk events
      {
        Effect = "Allow"
        Action = [
          "events:PutEvents"
        ]
        Resource = "arn:aws:events:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:event-bus/default"
      }
    ]
  })
}

# Lambda Function
resource "aws_lambda_function" "ingestor" {
  filename         = "${path.module}/lambda_package.zip"
  source_code_hash = fileexists("${path.module}/lambda_package.zip") ? filebase64sha256("${path.module}/lambda_package.zip") : null
  function_name    = local.function_name
  role             = aws_iam_role.lambda_role.arn
  handler          = "lambda_function.lambda_handler"
  runtime          = "python3.11"
  timeout          = var.lambda_timeout_seconds
  memory_size      = var.lambda_memory_mb

  environment {
    variables = {
      TELEMETRY_TABLE        = var.telemetry_table_name
      HAZARD_ZONES_TABLE     = var.hazard_zones_table_name
      EVENT_BUS              = "default"
      ENABLE_NSDI_ENRICHMENT = var.enable_nsdi_enrichment ? "true" : "false"
      ENABLE_EVENTBRIDGE     = var.enable_eventbridge ? "true" : "false"
      LOG_LEVEL              = var.environment == "prod" ? "INFO" : "DEBUG"
      HAZARD_GEOHASH_INDEX   = var.geohash_index_name
      HAZARD_GEOHASH_KEY     = "geohash"
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.lambda_logs,
    aws_iam_role_policy.lambda_policy
  ]

  tags = local.common_tags
}

# Lambda Permission for API Gateway
resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingestor.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.main.execution_arn}/*/*/*"
}

# Data sources
data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

# Outputs
output "lambda_function_name" {
  description = "Name of the Lambda function"
  value       = aws_lambda_function.ingestor.function_name
}

output "lambda_function_arn" {
  description = "ARN of the Lambda function"
  value       = aws_lambda_function.ingestor.arn
}

output "lambda_invoke_arn" {
  description = "Invoke ARN of the Lambda function"
  value       = aws_lambda_function.ingestor.invoke_arn
}

output "lambda_role_arn" {
  description = "ARN of the Lambda execution role"
  value       = aws_iam_role.lambda_role.arn
}

output "cloudwatch_log_group" {
  description = "CloudWatch Log Group name"
  value       = aws_cloudwatch_log_group.lambda_logs.name
}
