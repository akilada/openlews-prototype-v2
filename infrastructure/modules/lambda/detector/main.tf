# Detector Lambda Module

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

locals {
  lambda_name = "${var.project_name}-${var.environment}-detector"
  alerts_table_name = "${var.project_name}-${var.environment}-alerts"
  sns_topic_name = "${var.project_name}-${var.environment}-alerts"
}

# Lambda Function
resource "aws_lambda_function" "detector" {
  function_name = local.lambda_name
  role          = aws_iam_role.detector_lambda.arn
  handler       = "lambda_function.lambda_handler"
  runtime       = "python3.11"
  timeout       = 300  # 5 minutes
  memory_size   = 512  # MB
  
  filename          = "${path.module}/lambda_package.zip"
  source_code_hash  = fileexists("${path.module}/lambda_package.zip") ? filebase64sha256("${path.module}/lambda_package.zip") : null

  environment {
    variables = {
      TELEMETRY_TABLE_NAME    = var.telemetry_table_name
      ALERTS_TABLE_NAME       = var.alerts_table_name
      RAG_LAMBDA_ARN          = var.rag_lambda_arn
      SNS_TOPIC_ARN           = var.alert_email != "" ? aws_sns_topic.alerts[0].arn : ""
      RISK_THRESHOLD          = var.risk_threshold
      BEDROCK_MODEL_ID        = var.bedrock_model_id
      POWERTOOLS_LOG_LEVEL    = var.lambda_log_level
      POWERTOOLS_SERVICE_NAME = "openlews-detector"
      PLACE_INDEX_NAME         = var.place_index_name
    }
  }

  tags = merge(var.tags, {
    Name = local.lambda_name
  })
}

# CloudWatch Logs
resource "aws_cloudwatch_log_group" "detector_logs" {
  name              = "/aws/lambda/${local.lambda_name}"
  retention_in_days = var.cloudwatch_log_retention_days

  tags = var.tags
}

# IAM Role for Lambda
resource "aws_iam_role" "detector_lambda" {
  name = "${local.lambda_name}-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
    }]
  })

  tags = var.tags
}

# IAM Policy for Lambda
resource "aws_iam_role_policy" "detector_lambda" {
  name = "${local.lambda_name}-policy"
  role = aws_iam_role.detector_lambda.id

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
        Resource = "arn:aws:logs:${var.aws_region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/lambda/${local.lambda_name}:*"
      },
      # DynamoDB - Telemetry table
      {
        Effect = "Allow"
        Action = [
          "dynamodb:Query",
          "dynamodb:Scan",
          "dynamodb:GetItem",
          "dynamodb:BatchGetItem"
        ]
        Resource = [
          "arn:aws:dynamodb:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${var.telemetry_table_name}",
          "arn:aws:dynamodb:${var.aws_region}:${data.aws_caller_identity.current.account_id}:table/${var.telemetry_table_name}/index/*"
        ]
      },
      # DynamoDB - Alerts table (read/write)
      {
        Effect = "Allow"
        Action = [
          "dynamodb:Query",
          "dynamodb:Scan",
          "dynamodb:GetItem",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem"
        ]
        Resource = [
          "${var.alerts_table_arn}",
          "${var.alerts_table_arn}/index/*"
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
      # Lambda - Invoke RAG Lambda
      {
        Effect = "Allow"
        Action = [
          "lambda:InvokeFunction"
        ]
        Resource = var.rag_lambda_arn
      },
      # Bedrock Model
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        Resource = "arn:aws:bedrock:${var.aws_region}::foundation-model/${var.bedrock_model_id}"
      },
      # AWS Marketplace for LLM 
      {
        Effect = "Allow"
        Action = [
          "aws-marketplace:ViewSubscriptions",
          "aws-marketplace:Subscribe",
          "aws-marketplace:Unsubscribe"
        ]
        Resource = ["*"]
      },
      # SNS - Publish alerts
      {
        Effect = "Allow"
        Action = [
          "sns:Publish"
        ]
        Resource = aws_sns_topic.alerts[0].arn
      },
      # Amazon Location: reverse geocode
      {
        Effect = "Allow"
        Action = [
          "geo:SearchPlaceIndexForPosition"
        ]
        Resource = var.place_index_arn
      }
    ]
  })
}

data "aws_caller_identity" "current" {}

# EventBridge Schedule (every 15 minutes)
resource "aws_cloudwatch_event_rule" "detector_schedule" {
  name                = "${local.lambda_name}-schedule"
  description         = "Trigger detector Lambda every 15 minutes"
  schedule_expression = var.schedule_expression

  tags = var.tags
}

resource "aws_cloudwatch_event_target" "detector_lambda" {
  rule      = aws_cloudwatch_event_rule.detector_schedule.name
  target_id = "DetectorLambda"
  arn       = aws_lambda_function.detector.arn
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.detector.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.detector_schedule.arn
}

# SNS Topic Policy
resource "aws_sns_topic_policy" "alerts" {
  count     = var.alert_email != "" ? 1 : 0

  arn = aws_sns_topic.alerts[0].arn

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = {
        Service = "lambda.amazonaws.com"
      }
      Action   = "SNS:Publish"
      Resource = aws_sns_topic.alerts[0].arn
      Condition = {
        StringEquals = {
          "AWS:SourceAccount" = data.aws_caller_identity.current.account_id
        }
      }
    }]
  })
}

# Email Subscription
resource "aws_sns_topic_subscription" "email" {
  count     = var.alert_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.alerts[0].arn
  protocol  = "email"
  endpoint  = var.alert_email
}

resource "aws_sns_topic" "alerts" {
  count = var.alert_email != "" ? 1 : 0
  name  = "${local.sns_topic_name}"
  
  tags = merge(var.tags, {
    Name = local.sns_topic_name
  })
}
