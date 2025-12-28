variable "project_name" {
  description = "Project name for resource naming"
  type        = string
}

variable "environment" {
  description = "Environment (dev, prod)"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "telemetry_table_name" {
  description = "Name of telemetry DynamoDB table"
  type        = string
}

variable "alerts_table_name" {
  description = "Name of alerts DynamoDB table"
  type        = string
}

variable "alerts_table_arn" {
  description = "Name of alerts DynamoDB table ARN"
  type        = string
}

variable "dynamodb_kms_arn" {
  description = "ARN of DynamoDb KMS key"
  type        = string
}

variable "rag_lambda_arn" {
  description = "ARN of RAG Query Lambda function"
  type        = string
}

variable "risk_threshold" {
  description = "Risk score threshold for LLM invocation (0.0-1.0)"
  type        = number
  default     = 0.6
}

variable "bedrock_model_id" {
  description = "Bedrock model ID for LLM reasoning"
  type        = string
  default     = "anthropic.claude-3-5-sonnet-20241022-v2:0"
}

variable "schedule_expression" {
  description = "EventBridge schedule expression (e.g., rate(15 minutes))"
  type        = string
  default     = "rate(15 minutes)"
}

variable "cloudwatch_log_retention_days" {
  description = "CloudWatch Logs retention period"
  type        = number
  default     = 30
}

variable "lambda_log_level" {
  description = "Lambda log level (DEBUG, INFO, WARNING, ERROR)"
  type        = string
  default     = "INFO"
}

variable "enable_point_in_time_recovery" {
  description = "Enable PITR for Alerts table"
  type        = bool
  default     = false
}

variable "alert_email" {
  description = "Email address for SNS alert subscriptions (optional)"
  type        = string
  default     = ""
}

variable "enable_bedrock_logging" {
  description = "Enable CloudWatch logging for Bedrock invocations (for debugging)"
  type        = bool
  default     = false
}

variable "place_index_name" {
  description = "Amazon location lookup service "
  type        = string
  default     = ""
}

variable "place_index_arn" {
  description = "Amazon location lookup service ARN "
  type        = string
  default     = ""
}


variable "tags" {
  description = "Resource tags"
  type        = map(string)
  default     = {}
}
