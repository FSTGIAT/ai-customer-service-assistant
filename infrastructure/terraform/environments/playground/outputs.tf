output "opensearch_endpoint" {
  description = "OpenSearch domain endpoint"
  value       = module.rag_evaluation.opensearch_endpoint
}

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = module.rag_evaluation.ecs_cluster_name
}

output "evaluation_service_ecr_url" {
  description = "ECR repository URL for evaluation service"
  value       = module.rag_evaluation.evaluation_service_ecr_url
}

output "sqs_queue_urls" {
  description = "SQS queue URLs"
  value       = module.rag_evaluation.sqs_queue_urls
}

output "vpc_id" {
  description = "VPC ID"
  value       = module.rag_evaluation.vpc_id
}
