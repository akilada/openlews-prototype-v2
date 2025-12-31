# S3 Buckets Module - Cost Optimized with Lifecycle Policies

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

variable "environment" {
  description = "Environment name"
  type        = string
}

variable "aws_region" { type = string }

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "enable_versioning" {
  description = "Enable S3 versioning (adds cost)"
  type        = bool
  default     = false
}

variable "tags" {
  type    = map(string)
  default = {}
}

# KMS Key for S3 Encryption
resource "aws_kms_key" "s3" {
  description             = "KMS key for S3 bucket encryption"
  deletion_window_in_days = 7
  enable_key_rotation     = true

  tags = {
    Name        = "${var.name_prefix}-s3-key"
    Environment = var.environment
  }
}

resource "aws_kms_alias" "s3" {
  name          = "alias/${var.name_prefix}-s3"
  target_key_id = aws_kms_key.s3.key_id
}

# Bucket 1: Historical Data & Documents
resource "aws_s3_bucket" "historical_data" {
  bucket = "${var.name_prefix}-historical-data"

  tags = {
    Name        = "${var.name_prefix}-historical-data"
    Purpose     = "Rainfall archives - NBRO reports - hazard maps"
    Environment = var.environment
  }
}

# Enable versioning
resource "aws_s3_bucket_versioning" "historical_data" {
  bucket = aws_s3_bucket.historical_data.id

  versioning_configuration {
    status = var.enable_versioning ? "Enabled" : "Suspended"
  }
}

# Server-side encryption
resource "aws_s3_bucket_server_side_encryption_configuration" "historical_data" {
  bucket = aws_s3_bucket.historical_data.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.s3.arn
    }
    bucket_key_enabled = true
  }
}

# Block public access
resource "aws_s3_bucket_public_access_block" "historical_data" {
  bucket = aws_s3_bucket.historical_data.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Lifecycle policy - Move to cheaper storage after 30 days
resource "aws_s3_bucket_lifecycle_configuration" "historical_data" {
  bucket = aws_s3_bucket.historical_data.id

  rule {
    id     = "move-to-glacier"
    status = "Enabled"

    filter {}

    # Move objects to Glacier Deep Archive after 30 days
    transition {
      days          = 30
      storage_class = "GLACIER_IR"
    }

    # Delete objects after 1 year
    expiration {
      days = 365
    }
  }

  rule {
    id     = "delete-incomplete-uploads"
    status = "Enabled"

    filter {}
    # Clean up incomplete multipart uploads after 7 days
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# Bucket 2: RAG Documents (Preprocessed for Vector DB)
resource "aws_s3_bucket" "rag_documents" {
  bucket = "${var.name_prefix}-rag-documents"

  tags = {
    Name        = "${var.name_prefix}-rag-documents"
    Purpose     = "Preprocessed documents for RAG ingestion"
    Environment = var.environment
  }
}

resource "aws_s3_bucket_versioning" "rag_documents" {
  bucket = aws_s3_bucket.rag_documents.id

  versioning_configuration {
    status = "Suspended"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "rag_documents" {
  bucket = aws_s3_bucket.rag_documents.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.s3.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "rag_documents" {
  bucket = aws_s3_bucket.rag_documents.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Lifecycle: Delete old embeddings after 90 days
resource "aws_s3_bucket_lifecycle_configuration" "rag_documents" {
  bucket = aws_s3_bucket.rag_documents.id

  rule {
    id     = "expire-old-embeddings"
    status = "Enabled"

    filter {
      prefix = "embeddings/"
    }

    expiration {
      days = 90
    }
  }
}

# Bucket 3: Lambda Deployment Packages
resource "aws_s3_bucket" "lambda_artifacts" {
  bucket = "${var.name_prefix}-lambda-artifacts"

  tags = {
    Name        = "${var.name_prefix}-lambda-artifacts"
    Purpose     = "Lambda function deployment packages"
    Environment = var.environment
  }
}

resource "aws_s3_bucket_versioning" "lambda_artifacts" {
  bucket = aws_s3_bucket.lambda_artifacts.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "lambda_artifacts" {
  bucket = aws_s3_bucket.lambda_artifacts.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.s3.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "lambda_artifacts" {
  bucket = aws_s3_bucket.lambda_artifacts.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Lifecycle: Keep only last 5 versions
resource "aws_s3_bucket_lifecycle_configuration" "lambda_artifacts" {
  bucket = aws_s3_bucket.lambda_artifacts.id

  rule {
    id     = "limit-versions"
    status = "Enabled"

    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

# Outputs
output "historical_data_bucket_name" {
  description = "Name of historical data S3 bucket"
  value       = aws_s3_bucket.historical_data.bucket
}

output "historical_data_bucket_arn" {
  description = "ARN of historical data S3 bucket"
  value       = aws_s3_bucket.historical_data.arn
}

output "rag_documents_bucket_name" {
  description = "Name of RAG documents S3 bucket"
  value       = aws_s3_bucket.rag_documents.bucket
}

output "rag_documents_bucket_arn" {
  description = "ARN of RAG documents S3 bucket"
  value       = aws_s3_bucket.rag_documents.arn
}

output "lambda_artifacts_bucket_name" {
  description = "Name of Lambda artifacts S3 bucket"
  value       = aws_s3_bucket.lambda_artifacts.bucket
}

output "lambda_artifacts_bucket_arn" {
  description = "ARN of Lambda artifacts S3 bucket"
  value       = aws_s3_bucket.lambda_artifacts.arn
}

output "kms_key_id" {
  description = "KMS key ID for S3 encryption"
  value       = aws_kms_key.s3.id
}

output "kms_key_arn" {
  description = "KMS key ARN for S3 encryption"
  value       = aws_kms_key.s3.arn
}
