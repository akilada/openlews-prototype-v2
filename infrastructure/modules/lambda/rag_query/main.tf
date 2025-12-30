# RAG Query Lambda - Terraform Module
# Connects sensor locations to NDIS hazard zones

terraform {
  required_version = ">= 1.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

variable "environment" {
  description = "Environment name (dev, prod)"
  type        = string
}

variable "project_name" {
  description = "Project name"
  type        = string
}

variable "dynamodb_table_name" {
  description = "DynamoDB table for hazard zones"
  type        = string
}

variable "dynamodb_kms_arn" {
  description = "ARN of DynamoDb KMS key"
  type        = string
}

variable "s3_artifacts_bucket" {
  description = "S3 bucket for Lambda artifacts"
  type        = string
}

variable "pinecone_api_key_secret_name" {
  description = "Name of Secrets Manager secret containing Pinecone API key"
  type        = string
  default     = "pinecone/api-key"
}

variable "pinecone_index_name" {
  description = "Pinecone index name"
  type        = string
  default     = "lews-geological-knowledge"
}

variable "pinecone_namespace" {
  description = "Pinecone namespace"
  type        = string
  default     = "openlews"
}

variable "allowed_invokers" {
  description = "Map of invoker name to IAM role ARN"
  type        = map(string)
  default     = {}
}

variable "geohash_index_name" {
  description = "Name of geohash GSI on hazard zones table"
  type        = string
  default     = "GeoHashIndex"
}

variable "geohash_precision" {
  description = "Geohash precision to use when querying hazard zones"
  type        = number
  default     = 4
}

variable "tags" {
  type    = map(string)
  default = {}
}

# Data sources
data "aws_region" "current" {}
data "aws_caller_identity" "current" {}

# IAM Role for Lambda
resource "aws_iam_role" "rag_query_lambda" {
  name = "${var.project_name}-${var.environment}-rag-query-lambda-role"

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

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# IAM Policy for Lambda
resource "aws_iam_role_policy" "rag_query_lambda" {
  name = "${var.project_name}-${var.environment}-rag-query-lambda-policy"
  role = aws_iam_role.rag_query_lambda.id

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
        Resource = "arn:aws:logs:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:*"
      },
      # DynamoDB Read
      {
        Effect = "Allow"
        Action = [
          "dynamodb:Query",
          "dynamodb:GetItem",
          "dynamodb:BatchGetItem"
        ]
        Resource = [
          "arn:aws:dynamodb:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:table/${var.dynamodb_table_name}",
          "arn:aws:dynamodb:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:table/${var.dynamodb_table_name}/index/*"
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
      # Secrets Manager (Pinecone API Key)
      {
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = "arn:aws:secretsmanager:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:secret:${var.project_name}-${var.environment}/${var.pinecone_api_key_secret_name}*"
      }
    ]
  })
}

# CloudWatch Log Group
resource "aws_cloudwatch_log_group" "rag_query_lambda" {
  name              = "/aws/lambda/${var.project_name}-${var.environment}-rag-query"
  retention_in_days = 7

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# Lambda Function
resource "aws_lambda_function" "rag_query" {
  function_name = "${var.project_name}-${var.environment}-rag-query"
  role          = aws_iam_role.rag_query_lambda.arn
  handler       = "lambda_function.lambda_handler"
  runtime       = "python3.11"
  timeout       = 30
  memory_size   = 512

  filename         = "${path.module}/lambda_package.zip"
  source_code_hash = fileexists("${path.module}/lambda_package.zip") ? filebase64sha256("${path.module}/lambda_package.zip") : null

  environment {
    variables = {
      DYNAMODB_TABLE_NAME  = var.dynamodb_table_name
      PINECONE_INDEX_NAME  = var.pinecone_index_name
      PINECONE_NAMESPACE   = var.pinecone_namespace
      PINECONE_SECRET_NAME = "${var.project_name}-${var.environment}/${var.pinecone_api_key_secret_name}"
      GEOHASH_INDEX_NAME   = var.geohash_index_name
      GEOHASH_PRECISION    = tostring(var.geohash_precision)
    }
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }

  depends_on = [
    aws_cloudwatch_log_group.rag_query_lambda
  ]
}

# Lambda Function URL (for direct HTTPS invocation)
resource "aws_lambda_function_url" "rag_query" {
  function_name      = aws_lambda_function.rag_query.function_name
  authorization_type = "AWS_IAM"

  cors {
    allow_credentials = false
    allow_origins     = ["*"]
    allow_methods     = ["POST", "GET"]
    allow_headers     = ["*"]
    max_age           = 300
  }
}

resource "aws_lambda_permission" "function_url_invoke" {
  for_each = var.allowed_invokers

  statement_id           = "AllowInvoke-${each.key}"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.rag_query.function_name
  principal              = each.value
  function_url_auth_type = "AWS_IAM"

  lifecycle {
    create_before_destroy = true
  }
}

# Outputs
output "lambda_function_name" {
  description = "Name of the Lambda function"
  value       = aws_lambda_function.rag_query.function_name
}

output "lambda_function_arn" {
  description = "ARN of the Lambda function"
  value       = aws_lambda_function.rag_query.arn
}

output "lambda_function_url" {
  description = "HTTPS URL for invoking the Lambda"
  value       = aws_lambda_function_url.rag_query.function_url
}

output "lambda_role_arn" {
  description = "ARN of the Lambda execution role"
  value       = aws_iam_role.rag_query_lambda.arn
}

output "lambda_role_name" {
  description = "Name of the Lambda execution role"
  value       = aws_iam_role.rag_query_lambda.name
}
