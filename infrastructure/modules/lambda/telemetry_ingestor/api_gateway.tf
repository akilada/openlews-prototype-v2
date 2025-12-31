# API Gateway for Ingestor Lambda
# Creates REST API with /telemetry POST endpoint

# REST API
resource "aws_api_gateway_rest_api" "main" {
  name        = "${var.project_name}-${var.environment}-ingestor-api"
  description = "OpenLEWS Ingestor API for sensor telemetry ingestion"

  endpoint_configuration {
    types = ["REGIONAL"]
  }

  tags = local.common_tags
}

# /telemetry resource
resource "aws_api_gateway_resource" "telemetry" {
  rest_api_id = aws_api_gateway_rest_api.main.id
  parent_id   = aws_api_gateway_rest_api.main.root_resource_id
  path_part   = "telemetry"
}

# POST method on /telemetry
resource "aws_api_gateway_method" "telemetry_post" {
  rest_api_id      = aws_api_gateway_rest_api.main.id
  resource_id      = aws_api_gateway_resource.telemetry.id
  http_method      = "POST"
  authorization    = "NONE"
  api_key_required = var.enable_api_key_auth

  request_parameters = {
    "method.request.header.Content-Type" = true
  }
}

# Integration with Lambda
resource "aws_api_gateway_integration" "telemetry_lambda" {
  rest_api_id             = aws_api_gateway_rest_api.main.id
  resource_id             = aws_api_gateway_resource.telemetry.id
  http_method             = aws_api_gateway_method.telemetry_post.http_method
  integration_http_method = "POST"
  type                    = "AWS_PROXY"
  uri                     = aws_lambda_function.ingestor.invoke_arn
}

# CORS support - OPTIONS method
resource "aws_api_gateway_method" "telemetry_options" {
  rest_api_id   = aws_api_gateway_rest_api.main.id
  resource_id   = aws_api_gateway_resource.telemetry.id
  http_method   = "OPTIONS"
  authorization = "NONE"
}

resource "aws_api_gateway_integration" "telemetry_options" {
  rest_api_id = aws_api_gateway_rest_api.main.id
  resource_id = aws_api_gateway_resource.telemetry.id
  http_method = aws_api_gateway_method.telemetry_options.http_method
  type        = "MOCK"

  request_templates = {
    "application/json" = "{\"statusCode\": 200}"
  }
}

resource "aws_api_gateway_method_response" "telemetry_options_200" {
  rest_api_id = aws_api_gateway_rest_api.main.id
  resource_id = aws_api_gateway_resource.telemetry.id
  http_method = aws_api_gateway_method.telemetry_options.http_method
  status_code = "200"

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = true
    "method.response.header.Access-Control-Allow-Methods" = true
    "method.response.header.Access-Control-Allow-Origin"  = true
  }

  response_models = {
    "application/json" = "Empty"
  }
}

resource "aws_api_gateway_integration_response" "telemetry_options" {
  rest_api_id = aws_api_gateway_rest_api.main.id
  resource_id = aws_api_gateway_resource.telemetry.id
  http_method = aws_api_gateway_method.telemetry_options.http_method
  status_code = aws_api_gateway_method_response.telemetry_options_200.status_code

  response_parameters = {
    "method.response.header.Access-Control-Allow-Headers" = "'Content-Type,X-Amz-Date,Authorization,X-Api-Key,X-Amz-Security-Token'"
    "method.response.header.Access-Control-Allow-Methods" = "'POST,OPTIONS'"
    "method.response.header.Access-Control-Allow-Origin"  = "'*'"
  }

  depends_on = [aws_api_gateway_integration.telemetry_options]
}

# Deployment
resource "aws_api_gateway_deployment" "main" {
  rest_api_id = aws_api_gateway_rest_api.main.id

  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_resource.telemetry.id,
      aws_api_gateway_method.telemetry_post.id,
      aws_api_gateway_integration.telemetry_lambda.id,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }

  depends_on = [
    aws_api_gateway_integration.telemetry_lambda,
    aws_api_gateway_integration.telemetry_options
  ]
}

# Stage
resource "aws_api_gateway_stage" "main" {
  deployment_id = aws_api_gateway_deployment.main.id
  rest_api_id   = aws_api_gateway_rest_api.main.id
  stage_name    = var.environment

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_logs.arn
    format = jsonencode({
      requestId      = "$context.requestId"
      ip             = "$context.identity.sourceIp"
      caller         = "$context.identity.caller"
      user           = "$context.identity.user"
      requestTime    = "$context.requestTime"
      httpMethod     = "$context.httpMethod"
      resourcePath   = "$context.resourcePath"
      status         = "$context.status"
      protocol       = "$context.protocol"
      responseLength = "$context.responseLength"
    })
  }

  tags = local.common_tags

  depends_on = [aws_api_gateway_account.main]
}

# CloudWatch Logs for API Gateway
resource "aws_cloudwatch_log_group" "api_logs" {
  name              = "/aws/apigateway/${var.project_name}-ingestor-${var.environment}"
  retention_in_days = var.cloudwatch_log_retention_days

  tags = local.common_tags
}

# Usage Plan (for rate limiting)
resource "aws_api_gateway_usage_plan" "main" {
  name        = "${var.project_name}-ingestor-${var.environment}"
  description = "Usage plan for OpenLEWS Ingestor API"

  api_stages {
    api_id = aws_api_gateway_rest_api.main.id
    stage  = aws_api_gateway_stage.main.stage_name
  }

  quota_settings {
    limit  = var.api_quota_limit
    period = "MONTH"
  }

  throttle_settings {
    burst_limit = var.api_burst_limit
    rate_limit  = var.api_rate_limit
  }

  tags = local.common_tags
}

# API Key
resource "aws_api_gateway_api_key" "simulator" {
  count = var.enable_api_key_auth ? 1 : 0

  name        = "${var.project_name}-simulator-${var.environment}"
  description = "API key for OpenLEWS simulator"
  enabled     = true

  tags = merge(
    local.common_tags,
    {
      Client = "Simulator"
    }
  )
}

# Associate API Key with Usage Plan
resource "aws_api_gateway_usage_plan_key" "simulator" {
  count = var.enable_api_key_auth ? 1 : 0

  key_id        = aws_api_gateway_api_key.simulator[0].id
  key_type      = "API_KEY"
  usage_plan_id = aws_api_gateway_usage_plan.main.id
}

# Store API Key in Secrets Manager
resource "aws_secretsmanager_secret" "api_key" {
  count = var.enable_api_key_auth ? 1 : 0

  name        = "${var.project_name}-${var.environment}/ingestor/api-key"
  description = "API Gateway key for OpenLEWS Ingestor"

  recovery_window_in_days = 7

  tags = local.common_tags
}

resource "aws_secretsmanager_secret_version" "api_key" {
  count = var.enable_api_key_auth ? 1 : 0

  secret_id     = aws_secretsmanager_secret.api_key[0].id
  secret_string = aws_api_gateway_api_key.simulator[0].value
}

# API Gateway Account-level CloudWatch Role
resource "aws_iam_role" "api_gateway_cloudwatch" {
  name = "${var.project_name}-${var.environment}-apigw-cloudwatch"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action = "sts:AssumeRole"
      Effect = "Allow"
      Principal = {
        Service = "apigateway.amazonaws.com"
      }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "api_gateway_cloudwatch" {
  role       = aws_iam_role.api_gateway_cloudwatch.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonAPIGatewayPushToCloudWatchLogs"
}

resource "aws_api_gateway_account" "main" {
  cloudwatch_role_arn = aws_iam_role.api_gateway_cloudwatch.arn
}

# Outputs
output "api_gateway_id" {
  description = "ID of the API Gateway"
  value       = aws_api_gateway_rest_api.main.id
}

output "api_gateway_endpoint" {
  description = "Full endpoint URL for the API"
  value       = "${aws_api_gateway_stage.main.invoke_url}/telemetry"
}

output "api_gateway_stage_name" {
  description = "API Gateway stage name"
  value       = aws_api_gateway_stage.main.stage_name
}

output "api_gateway_execution_arn" {
  description = "Execution ARN of the API Gateway"
  value       = aws_api_gateway_rest_api.main.execution_arn
}

output "api_key_id" {
  description = "ID of the API key (if enabled)"
  value       = var.enable_api_key_auth ? aws_api_gateway_api_key.simulator[0].id : null
}

output "api_key_secret_arn" {
  description = "ARN of Secrets Manager secret containing API key"
  value       = var.enable_api_key_auth ? aws_secretsmanager_secret.api_key[0].arn : null
  sensitive   = true
}

output "api_key_value" {
  description = "API key value (sensitive - use for initial setup only)"
  value       = var.enable_api_key_auth ? aws_api_gateway_api_key.simulator[0].value : null
  sensitive   = true
}
