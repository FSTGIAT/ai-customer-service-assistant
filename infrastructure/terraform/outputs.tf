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

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = module.ecs_gpu_cluster.cluster_name
}

output "ecs_cluster_arn" {
  description = "ECS cluster ARN"
  value       = module.ecs_gpu_cluster.cluster_arn
}

output "evaluation_service_ecr_url" {
  description = "ECR repository URL for evaluation service"
  value       = module.evaluation_service.ecr_repository_url
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
