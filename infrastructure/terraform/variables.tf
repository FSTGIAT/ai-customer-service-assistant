variable "aws_region" {
  description = "AWS region for resources"
  type        = string
  default     = "eu-west-1"
}

variable "environment" {
  description = "Environment name (playground, production)"
  type        = string
  default     = "playground"
}

variable "project_name" {
  description = "Project name for resource naming"
  type        = string
  default     = "call-analytics"
}

# VPC Configuration
variable "vpc_cidr" {
  description = "CIDR block for VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "availability_zones" {
  description = "List of availability zones"
  type        = list(string)
  default     = ["eu-west-1a", "eu-west-1b"]
}

# OpenSearch Configuration
variable "opensearch_instance_type" {
  description = "OpenSearch instance type"
  type        = string
  default     = "r5.large.search"
}

variable "opensearch_instance_count" {
  description = "Number of OpenSearch instances"
  type        = number
  default     = 2
}

variable "opensearch_ebs_volume_size" {
  description = "EBS volume size for OpenSearch (GB)"
  type        = number
  default     = 100
}

variable "opensearch_version" {
  description = "OpenSearch engine version"
  type        = string
  default     = "OpenSearch_2.11"
}

# ECS Configuration
variable "ecs_gpu_instance_type" {
  description = "EC2 instance type for GPU workloads"
  type        = string
  default     = "g4dn.xlarge"
}

variable "ecs_gpu_min_size" {
  description = "Minimum number of GPU instances"
  type        = number
  default     = 1
}

variable "ecs_gpu_max_size" {
  description = "Maximum number of GPU instances"
  type        = number
  default     = 2
}

variable "ecs_gpu_desired_size" {
  description = "Desired number of GPU instances"
  type        = number
  default     = 1
}

# ECR Configuration
variable "ecr_repositories" {
  description = "List of ECR repositories to create"
  type        = list(string)
  default = [
    "ml-service",
    "evaluation-service",
    "api-service"
  ]
}

# SQS Configuration
variable "sqs_message_retention_seconds" {
  description = "SQS message retention in seconds"
  type        = number
  default     = 345600  # 4 days
}

variable "sqs_visibility_timeout_seconds" {
  description = "SQS visibility timeout in seconds"
  type        = number
  default     = 300  # 5 minutes
}

# Use Existing Resources (to avoid permission/limit issues)
variable "use_existing_vpc" {
  description = "Whether to use an existing VPC instead of creating a new one"
  type        = bool
  default     = false
}

variable "existing_vpc_id" {
  description = "ID of existing VPC to use (required if use_existing_vpc is true)"
  type        = string
  default     = ""
}

variable "existing_private_subnet_ids" {
  description = "List of existing private subnet IDs"
  type        = list(string)
  default     = []
}

variable "existing_public_subnet_ids" {
  description = "List of existing public subnet IDs"
  type        = list(string)
  default     = []
}

variable "use_existing_iam_roles" {
  description = "Whether to use existing IAM roles instead of creating new ones"
  type        = bool
  default     = false
}

variable "existing_ecs_instance_role_arn" {
  description = "ARN of existing ECS instance role"
  type        = string
  default     = ""
}

variable "existing_ecs_task_execution_role_arn" {
  description = "ARN of existing ECS task execution role"
  type        = string
  default     = ""
}

variable "existing_ecs_task_role_arn" {
  description = "ARN of existing ECS task role (optional, can be same as execution role)"
  type        = string
  default     = ""
}

variable "existing_ecs_instance_profile_arn" {
  description = "ARN of existing ECS instance profile"
  type        = string
  default     = ""
}

# Lambda/ECS Selection
variable "enable_ecs_gpu_cluster" {
  description = "Whether to create ECS GPU cluster (disable to use Lambda only)"
  type        = bool
  default     = false  # Default to Lambda-based evaluation
}

# OpenSearch Authentication
variable "opensearch_master_user" {
  description = "OpenSearch master username"
  type        = string
  default     = "admin"
  sensitive   = true
}

variable "opensearch_master_password" {
  description = "OpenSearch master password"
  type        = string
  default     = ""
  sensitive   = true
}

# Use existing Lambda execution role (to avoid IAM CreateRole permission requirement)
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
