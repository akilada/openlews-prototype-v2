# Amazon Bedrock Configuration
# Note: Bedrock model access must be requested through AWS Console first.

# Data source to verify model availability
data "aws_bedrock_foundation_model" "claude_sonnet" {
  model_id = var.bedrock_model_id
}

# CloudWatch Log Group for Bedrock invocations
resource "aws_cloudwatch_log_group" "bedrock_invocations" {
  count             = var.enable_bedrock_logging ? 1 : 0
  name              = "/aws/bedrock/openlews/${var.environment}"
  retention_in_days = 7

  tags = var.tags
}

# Optional: Custom Bedrock model invocation logging role
resource "aws_iam_role" "bedrock_logging" {
  count = var.enable_bedrock_logging ? 1 : 0
  name  = "${local.lambda_name}-bedrock-logging"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "bedrock.amazonaws.com"
      }
    }]
  })

  tags = var.tags
}

resource "aws_iam_role_policy" "bedrock_logging" {
  count = var.enable_bedrock_logging ? 1 : 0
  name  = "bedrock-cloudwatch-logs"
  role  = aws_iam_role.bedrock_logging[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "${aws_cloudwatch_log_group.bedrock_invocations[0].arn}:*"
      }
    ]
  })
}


# Cost tracking tags for Bedrock usage
locals {
  bedrock_tags = merge(var.tags, {
    BedrockModel = var.bedrock_model_id
    CostCenter   = "OpenLEWS-LLM"
  })
}
