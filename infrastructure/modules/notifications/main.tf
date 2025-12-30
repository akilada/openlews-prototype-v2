terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = ">= 2.4"
    }
  }
}

provider "aws" {
  region = var.region
}

locals {
  name_prefix = "${var.project_name}-${var.environment}"
}

resource "aws_sesv2_email_identity" "from" {
  email_identity = var.ses_from_email
  tags           = var.tags
}

data "archive_file" "zip" {
  type        = "zip"
  source_file = "${path.module}/lambda/sns_to_ses_emailer.py"
  output_path = "${path.module}/build/sns_to_ses_emailer.zip"
}

resource "aws_iam_role" "lambda_role" {
  name = "${local.name_prefix}-sns-to-ses-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action = "sts:AssumeRole"
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy" "lambda_policy" {
  name = "${local.name_prefix}-sns-to-ses-policy"
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
        Resource = "*"
      },
      # SES send
      {
        Effect = "Allow"
        Action = [
          "ses:SendEmail",
          "ses:SendRawEmail",
          "ses:SendTemplatedEmail"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_lambda_function" "sns_to_ses" {
  function_name = "${local.name_prefix}-sns-to-ses-emailer"
  role          = aws_iam_role.lambda_role.arn
  handler       = "sns_to_ses_emailer.lambda_handler"
  runtime       = "python3.11"
  timeout       = 15

  filename         = data.archive_file.zip.output_path
  source_code_hash = data.archive_file.zip.output_base64sha256

  environment {
    variables = {
      AWS_REGION       = var.region
      SES_FROM_EMAIL   = var.ses_from_email
      SES_TO_EMAILS    = join(",", var.ses_to_emails)
      TIMEZONE         = var.timezone
      APP_NAME         = "OpenLEWS"
      GOOGLE_MAPS_ZOOM = "16"
    }
  }

  tags = var.tags
}

# Allow SNS to invoke Lambda
resource "aws_lambda_permission" "allow_sns" {
  statement_id  = "AllowExecutionFromSNS"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.sns_to_ses.function_name
  principal     = "sns.amazonaws.com"
  source_arn    = var.sns_topic_arn
}

# Subscribe Lambda to alert topic
resource "aws_sns_topic_subscription" "lambda_sub" {
  topic_arn = var.sns_topic_arn
  protocol  = "lambda"
  endpoint  = aws_lambda_function.sns_to_ses.arn
}
