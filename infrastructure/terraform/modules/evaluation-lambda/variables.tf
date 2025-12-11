# Variables for Lambda Evaluation Module

variable "name_prefix" {
  description = "Prefix for resource names"
  type        = string
}

variable "aws_region" {
  description = "AWS region"
  type        = string
}

variable "subnet_ids" {
  description = "Subnet IDs for Lambda VPC config"
  type        = list(string)
}

variable "security_group_ids" {
  description = "Security group IDs for Lambda"
  type        = list(string)
}

variable "opensearch_endpoint" {
  description = "OpenSearch domain endpoint"
  type        = string
}

variable "opensearch_arn" {
  description = "OpenSearch domain ARN"
  type        = string
}

variable "opensearch_user" {
  description = "OpenSearch master user"
  type        = string
  sensitive   = true
}

variable "opensearch_password" {
  description = "OpenSearch master password"
  type        = string
  sensitive   = true
}

variable "evaluation_queue_arn" {
  description = "ARN of the evaluation SQS queue"
  type        = string
}

variable "feedback_queue_arn" {
  description = "ARN of the feedback SQS queue"
  type        = string
}

variable "feedback_queue_url" {
  description = "URL of the feedback SQS queue"
  type        = string
}

variable "sqs_queue_arns" {
  description = "List of all SQS queue ARNs for IAM policy"
  type        = list(string)
}

variable "tags" {
  description = "Tags for resources"
  type        = map(string)
  default     = {}
}

# Use existing Lambda role (to avoid IAM CreateRole permission requirement)
variable "use_existing_lambda_role" {
  description = "Whether to use an existing Lambda execution role"
  type        = bool
  default     = false
}

variable "existing_lambda_role_arn" {
  description = "ARN of existing Lambda execution role (required if use_existing_lambda_role is true)"
  type        = string
  default     = ""
}
