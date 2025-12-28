# AWS Secrets Manager Module - Secure API Key Storage

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

variable "aws_region"  { type = string }

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "rotation_days" {
  description = "Days between automatic secret rotation"
  type        = number
  default     = 90
}

variable "tags" {
  type    = map(string)
  default = {}
}

# KMS Key for Secrets Encryption
resource "aws_kms_key" "secrets" {
  description             = "KMS key for Secrets Manager encryption"
  deletion_window_in_days = 7
  enable_key_rotation     = true

  tags = {
    Name        = "${var.name_prefix}-secrets-key"
    Environment = var.environment
  }
}

resource "aws_kms_alias" "secrets" {
  name          = "alias/${var.name_prefix}-secrets"
  target_key_id = aws_kms_key.secrets.key_id
}

# Secret 1: Pinecone API Key
resource "aws_secretsmanager_secret" "pinecone_api_key" {
  name                    = "${var.name_prefix}/pinecone/api-key"
  description             = "Pinecone Vector DB API key"
  kms_key_id              = aws_kms_key.secrets.id
  recovery_window_in_days = 7

  tags = {
    Name        = "${var.name_prefix}-pinecone-api-key"
    Purpose     = "Vector DB authentication"
    Environment = var.environment
  }
}

# Placeholder secret value
resource "aws_secretsmanager_secret_version" "pinecone_api_key" {
  secret_id = aws_secretsmanager_secret.pinecone_api_key.id
  secret_string = jsonencode({
    api_key     = "PLACEHOLDER_REPLACE_AFTER_DEPLOY"
    environment = "us-east-1"  # Pinecone region
    index_name  = "lews-geological-knowledge"
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
}

# Secret 2: ThingsBoard Access Token
resource "aws_secretsmanager_secret" "thingsboard_token" {
  name                    = "${var.name_prefix}/thingsboard/access-token"
  description             = "ThingsBoard device access token"
  kms_key_id              = aws_kms_key.secrets.id
  recovery_window_in_days = 7

  tags = {
    Name        = "${var.name_prefix}-thingsboard-token"
    Purpose     = "IoT platform authentication"
    Environment = var.environment
  }
}

resource "aws_secretsmanager_secret_version" "thingsboard_token" {
  secret_id = aws_secretsmanager_secret.thingsboard_token.id
  secret_string = jsonencode({
    access_token = "PLACEHOLDER_REPLACE_AFTER_DEPLOY"
    mqtt_host    = "mqtt.thingsboard.cloud"
    mqtt_port    = 1883
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
}

# Secret 3: Database Connection String
resource "aws_secretsmanager_secret" "database_credentials" {
  name                    = "${var.name_prefix}/database/credentials"
  description             = "Database connection credentials (future use)"
  kms_key_id              = aws_kms_key.secrets.id
  recovery_window_in_days = 7

  tags = {
    Name        = "${var.name_prefix}-database-credentials"
    Purpose     = "Database authentication"
    Environment = var.environment
  }
}

resource "aws_secretsmanager_secret_version" "database_credentials" {
  secret_id = aws_secretsmanager_secret.database_credentials.id
  secret_string = jsonencode({
    username = "openlews_admin"
    password = "PLACEHOLDER_REPLACE_AFTER_DEPLOY"
    host     = "localhost"
    port     = 5432
    database = "openlews"
  })

  lifecycle {
    ignore_changes = [secret_string]
  }
}

# IAM Policy for Lambda to read secrets
data "aws_iam_policy_document" "lambda_secrets_read" {
  statement {
    sid    = "ReadSecrets"
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret"
    ]
    resources = [
      aws_secretsmanager_secret.pinecone_api_key.arn,
      aws_secretsmanager_secret.thingsboard_token.arn,
      aws_secretsmanager_secret.database_credentials.arn
    ]
  }

  statement {
    sid    = "DecryptSecrets"
    effect = "Allow"
    actions = [
      "kms:Decrypt",
      "kms:DescribeKey"
    ]
    resources = [aws_kms_key.secrets.arn]
  }
}

resource "aws_iam_policy" "lambda_secrets_read" {
  name        = "${var.name_prefix}-lambda-secrets-read"
  description = "Allow Lambda functions to read secrets"
  policy      = data.aws_iam_policy_document.lambda_secrets_read.json

  tags = {
    Name        = "${var.name_prefix}-lambda-secrets-read"
    Environment = var.environment
  }
}

# Outputs
output "pinecone_secret_arn" {
  description = "ARN of Pinecone API key secret"
  value       = aws_secretsmanager_secret.pinecone_api_key.arn
}

output "thingsboard_secret_arn" {
  description = "ARN of ThingsBoard token secret"
  value       = aws_secretsmanager_secret.thingsboard_token.arn
}

output "database_secret_arn" {
  description = "ARN of database credentials secret"
  value       = aws_secretsmanager_secret.database_credentials.arn
}

output "kms_key_id" {
  description = "KMS key ID for secrets encryption"
  value       = aws_kms_key.secrets.id
}

output "kms_key_arn" {
  description = "KMS key ARN for secrets encryption"
  value       = aws_kms_key.secrets.arn
}

output "lambda_secrets_policy_arn" {
  description = "IAM policy ARN for Lambda to read secrets"
  value       = aws_iam_policy.lambda_secrets_read.arn
}

output "secret_names" {
  description = "Map of secret names for easy reference"
  value = {
    pinecone     = aws_secretsmanager_secret.pinecone_api_key.name
    thingsboard  = aws_secretsmanager_secret.thingsboard_token.name
    database     = aws_secretsmanager_secret.database_credentials.name
  }
}
