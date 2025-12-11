# Outputs for Lambda Evaluation Module

output "lambda_function_arn" {
  description = "ARN of the evaluation Lambda function"
  value       = aws_lambda_function.evaluation.arn
}

output "lambda_function_name" {
  description = "Name of the evaluation Lambda function"
  value       = aws_lambda_function.evaluation.function_name
}

output "lambda_role_arn" {
  description = "ARN of the Lambda execution role"
  value       = local.lambda_role_arn
}

output "cloudwatch_dashboard_name" {
  description = "Name of the CloudWatch dashboard"
  value       = aws_cloudwatch_dashboard.evaluation_metrics.dashboard_name
}

output "log_group_name" {
  description = "Name of the CloudWatch log group"
  value       = aws_cloudwatch_log_group.evaluation_lambda.name
}
