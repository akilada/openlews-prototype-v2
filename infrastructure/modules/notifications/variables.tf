variable "project_name" { type = string }
variable "environment"  { type = string }
variable "region"       { type = string }

variable "sns_topic_arn" {
  type        = string
  description = "SNS topic that publishes OpenLEWS alerts (JSON)"
}

variable "ses_from_email" {
  type        = string
  description = "Verified SES identity"
}

variable "ses_to_emails" {
  type        = list(string)
  description = "Recipient list"
}

variable "timezone" {
  type        = string
  default     = "Asia/Colombo"
  description = "Local Timezone display"
}

variable "tags" {
  type    = map(string)
  default = {}
}
