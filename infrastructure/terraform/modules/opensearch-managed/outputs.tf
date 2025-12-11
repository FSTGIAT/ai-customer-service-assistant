output "domain_id" {
  description = "ID of the OpenSearch domain"
  value       = aws_opensearch_domain.main.domain_id
}

output "domain_name" {
  description = "Name of the OpenSearch domain"
  value       = aws_opensearch_domain.main.domain_name
}

output "domain_endpoint" {
  description = "Endpoint of the OpenSearch domain"
  value       = aws_opensearch_domain.main.endpoint
}

output "domain_arn" {
  description = "ARN of the OpenSearch domain"
  value       = aws_opensearch_domain.main.arn
}

output "kibana_endpoint" {
  description = "Kibana/Dashboards endpoint"
  value       = aws_opensearch_domain.main.dashboard_endpoint
}
