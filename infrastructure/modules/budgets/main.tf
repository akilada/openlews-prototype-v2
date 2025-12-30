# AWS Budget Module - Cost Guardrails

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
variable "name_prefix" { type = string }

variable "monthly_budget_usd" {
  description = "Monthly budget limit in USD"
  type        = number
  default     = 15
}

variable "alert_email" {
  description = "Email address for budget alerts"
  type        = string
}

variable "alert_threshold_1" {
  description = "First alert threshold (USD)"
  type        = number
  default     = 7.5 # 50% of $7.5
}

variable "alert_threshold_2" {
  description = "Second alert threshold (USD)"
  type        = number
  default     = 12 # 80% of $12
}

variable "tags" {
  type    = map(string)
  default = {}
}

# SNS Topic for Budget Alerts
resource "aws_sns_topic" "budget_alerts" {
  name              = "openlews-${var.environment}-budget-alerts"
  display_name      = "OpenLEWS Budget Alerts"
  kms_master_key_id = aws_kms_key.sns_encryption.id

  tags = {
    Name        = "openlews-${var.environment}-budget-alerts"
    Purpose     = "Cost monitoring"
    Environment = var.environment
  }
}

# KMS Key for SNS Encryption
resource "aws_kms_key" "sns_encryption" {
  description             = "KMS key for SNS topic encryption"
  deletion_window_in_days = 7
  enable_key_rotation     = true

  tags = {
    Name        = "openlews-${var.environment}-sns-key"
    Environment = var.environment
  }
}

resource "aws_kms_alias" "sns_encryption" {
  name          = "alias/openlews-${var.environment}-sns"
  target_key_id = aws_kms_key.sns_encryption.key_id
}

# Email Subscription to SNS Topic
resource "aws_sns_topic_subscription" "budget_alerts_email" {
  topic_arn = aws_sns_topic.budget_alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}

# AWS Budget - Monthly Limit
resource "aws_budgets_budget" "monthly_cost" {
  name              = "openlews-${var.environment}-monthly-budget"
  budget_type       = "COST"
  limit_amount      = var.monthly_budget_usd
  limit_unit        = "USD"
  time_period_start = "2025-01-01_00:00"
  time_unit         = "MONTHLY"

  # Cost filters
  cost_filter {
    name = "TagKeyValue"
    values = [
      "Project$OpenLEWS",
    ]
  }

  # Alert at 50% of budget
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 50
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
    subscriber_sns_topic_arns  = [aws_sns_topic.budget_alerts.arn]
  }

  # Alert at 80% of budget
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
    subscriber_sns_topic_arns  = [aws_sns_topic.budget_alerts.arn]
  }

  # Alert at 100% of budget
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
    subscriber_sns_topic_arns  = [aws_sns_topic.budget_alerts.arn]
  }

  # Forecasted to exceed budget
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
    subscriber_sns_topic_arns  = [aws_sns_topic.budget_alerts.arn]
  }
}

# CloudWatch Alarm - Estimated Charges
resource "aws_cloudwatch_metric_alarm" "estimated_charges" {
  alarm_name          = "openlews-${var.environment}-estimated-charges"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = "1"
  metric_name         = "EstimatedCharges"
  namespace           = "AWS/Billing"
  period              = "21600" # 6 hours
  statistic           = "Maximum"
  threshold           = var.alert_threshold_1
  alarm_description   = "Alert when estimated monthly charges exceed ${var.alert_threshold_1} USD"
  alarm_actions       = [aws_sns_topic.budget_alerts.arn]

  dimensions = {
    Currency = "USD"
  }

  tags = {
    Name        = "openlews-${var.environment}-billing-alarm"
    Environment = var.environment
  }
}

# Output
output "budget_alert_topic_arn" {
  description = "ARN of SNS topic for budget alerts"
  value       = aws_sns_topic.budget_alerts.arn
}

output "budget_name" {
  description = "Name of the monthly budget"
  value       = aws_budgets_budget.monthly_cost.name
}

output "budget_limit" {
  description = "Monthly budget limit in USD"
  value       = aws_budgets_budget.monthly_cost.limit_amount
}
