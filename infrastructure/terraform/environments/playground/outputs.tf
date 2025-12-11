output "opensearch_endpoint" {
  description = "OpenSearch domain endpoint"
  value       = module.rag_evaluation.opensearch_endpoint
}

output "evaluation_lambda_function_name" {
  description = "Evaluation Lambda function name"
  value       = module.rag_evaluation.evaluation_lambda_function_name
}

output "evaluation_lambda_function_arn" {
  description = "Evaluation Lambda function ARN"
  value       = module.rag_evaluation.evaluation_lambda_function_arn
}

output "sqs_queue_urls" {
  description = "SQS queue URLs"
  value       = module.rag_evaluation.sqs_queue_urls
}

output "vpc_id" {
  description = "VPC ID"
  value       = module.rag_evaluation.vpc_id
}

output "cloudwatch_dashboard_url" {
  description = "CloudWatch dashboard URL"
  value       = module.rag_evaluation.cloudwatch_dashboard_url
}
