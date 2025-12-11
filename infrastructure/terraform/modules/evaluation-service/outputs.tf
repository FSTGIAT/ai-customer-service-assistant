output "ecr_repository_url" {
  description = "URL of the ECR repository"
  value       = aws_ecr_repository.evaluation_service.repository_url
}

output "task_definition_arn" {
  description = "ARN of the task definition"
  value       = aws_ecs_task_definition.evaluation_service.arn
}

output "service_name" {
  description = "Name of the ECS service"
  value       = aws_ecs_service.evaluation_service.name
}

output "cloudwatch_dashboard_arn" {
  description = "ARN of the CloudWatch dashboard"
  value       = aws_cloudwatch_dashboard.evaluation_metrics.dashboard_arn
}
