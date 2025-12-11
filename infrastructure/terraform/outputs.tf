# Root module outputs

output "vpc_id" {
  description = "ID of the VPC"
  value       = local.vpc_id
}

output "opensearch_endpoint" {
  description = "OpenSearch domain endpoint"
  value       = module.opensearch.domain_endpoint
}

output "opensearch_dashboard_endpoint" {
  description = "OpenSearch dashboard endpoint"
  value       = module.opensearch.kibana_endpoint
}

# ECS outputs (only if ECS GPU cluster is enabled)
output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = var.enable_ecs_gpu_cluster ? module.ecs_gpu_cluster[0].cluster_name : null
}

output "ecs_cluster_arn" {
  description = "ECS cluster ARN"
  value       = var.enable_ecs_gpu_cluster ? module.ecs_gpu_cluster[0].cluster_arn : null
}

# Lambda outputs
output "evaluation_lambda_function_name" {
  description = "Name of the evaluation Lambda function"
  value       = module.evaluation_lambda.lambda_function_name
}

output "evaluation_lambda_function_arn" {
  description = "ARN of the evaluation Lambda function"
  value       = module.evaluation_lambda.lambda_function_arn
}

output "sqs_queue_urls" {
  description = "SQS queue URLs"
  value = {
    keypoint   = module.sqs_queues.keypoint_queue_url
    evaluation = module.sqs_queues.evaluation_queue_url
    feedback   = module.sqs_queues.feedback_queue_url
  }
}

output "cloudwatch_dashboard_url" {
  description = "CloudWatch dashboard URL"
  value       = "https://${var.aws_region}.console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards:name=${local.name_prefix}-rag-evaluation"
}
