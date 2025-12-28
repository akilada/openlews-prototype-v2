output "lambda_function_arn" {
  description = "ARN of Detector Lambda function"
  value       = aws_lambda_function.detector.arn
}

output "lambda_function_name" {
  description = "Name of Detector Lambda function"
  value       = aws_lambda_function.detector.function_name
}

output "alerts_table_name" {
  description = "Name of Alerts DynamoDB table"
  value       = var.alerts_table_name
}

output "sns_topic_arn" {
  description = "ARN of Alerts SNS topic"
  value       = var.alert_email != "" ? aws_sns_topic.alerts[0].arn : null
}

output "sns_topic_name" {
  description = "Name of Alerts SNS topic"
  value       = var.alert_email != "" ? aws_sns_topic.alerts[0].name : null
}

output "schedule_rule_name" {
  description = "Name of EventBridge schedule rule"
  value       = aws_cloudwatch_event_rule.detector_schedule.name
}

output "bedrock_model_id" {
  description = "Bedrock model ID in use"
  value       = data.aws_bedrock_foundation_model.claude_sonnet.model_id
}

output "bedrock_model_arn" {
  description = "Bedrock model ARN"
  value       = data.aws_bedrock_foundation_model.claude_sonnet.model_arn
}

output "bedrock_provider_name" {
  description = "Model provider (should be Anthropic)"
  value       = data.aws_bedrock_foundation_model.claude_sonnet.provider_name
}

output "lambda_role_arn" {
  description = "ARN of the detector Lambda IAM role"
  value       = aws_iam_role.detector_lambda.arn
}