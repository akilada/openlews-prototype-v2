output "lambda_function_name" {
  value = aws_lambda_function.sns_to_ses.function_name
}

output "ses_identity_arn" {
  value = aws_sesv2_email_identity.from.arn
}
