# Main Terraform configuration for RAG Evaluation Infrastructure
# This builds the complete AWS infrastructure from scratch

locals {
  name_prefix = "${var.project_name}-${var.environment}"

  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

# =============================================================================
# NETWORKING
# =============================================================================

module "networking" {
  source = "./modules/networking"

  name_prefix        = local.name_prefix
  vpc_cidr           = var.vpc_cidr
  availability_zones = var.availability_zones

  tags = local.common_tags
}

# =============================================================================
# IAM POLICIES
# =============================================================================

module "iam_policies" {
  source = "./modules/iam-policies"

  name_prefix = local.name_prefix
  aws_region  = var.aws_region

  tags = local.common_tags
}

# =============================================================================
# AWS MANAGED OPENSEARCH
# =============================================================================

module "opensearch" {
  source = "./modules/opensearch-managed"

  name_prefix           = local.name_prefix
  domain_name           = "${local.name_prefix}-search"
  engine_version        = var.opensearch_version
  instance_type         = var.opensearch_instance_type
  instance_count        = var.opensearch_instance_count
  ebs_volume_size       = var.opensearch_ebs_volume_size

  vpc_id                = module.networking.vpc_id
  subnet_ids            = module.networking.private_subnet_ids
  security_group_ids    = [module.networking.opensearch_security_group_id]

  tags = local.common_tags
}

# =============================================================================
# SQS QUEUES
# =============================================================================

module "sqs_queues" {
  source = "./modules/sqs-queues"

  name_prefix                = local.name_prefix
  message_retention_seconds  = var.sqs_message_retention_seconds
  visibility_timeout_seconds = var.sqs_visibility_timeout_seconds

  tags = local.common_tags
}

# =============================================================================
# ECS GPU CLUSTER
# =============================================================================

module "ecs_gpu_cluster" {
  source = "./modules/ecs-gpu-cluster"

  name_prefix        = local.name_prefix
  vpc_id             = module.networking.vpc_id
  subnet_ids         = module.networking.private_subnet_ids
  security_group_ids = [module.networking.ecs_security_group_id]

  instance_type      = var.ecs_gpu_instance_type
  min_size           = var.ecs_gpu_min_size
  max_size           = var.ecs_gpu_max_size
  desired_size       = var.ecs_gpu_desired_size

  ecs_instance_role_arn     = module.iam_policies.ecs_instance_role_arn
  ecs_task_execution_role_arn = module.iam_policies.ecs_task_execution_role_arn
  ecs_task_role_arn         = module.iam_policies.ecs_task_role_arn

  tags = local.common_tags
}

# =============================================================================
# EVALUATION SERVICE
# =============================================================================

module "evaluation_service" {
  source = "./modules/evaluation-service"

  name_prefix = local.name_prefix

  ecs_cluster_id              = module.ecs_gpu_cluster.cluster_id
  ecs_task_execution_role_arn = module.iam_policies.ecs_task_execution_role_arn
  ecs_task_role_arn           = module.iam_policies.ecs_task_role_arn

  subnet_ids         = module.networking.private_subnet_ids
  security_group_ids = [module.networking.ecs_security_group_id]

  opensearch_endpoint     = module.opensearch.domain_endpoint
  evaluation_queue_url    = module.sqs_queues.evaluation_queue_url
  keypoint_queue_url      = module.sqs_queues.keypoint_queue_url
  feedback_queue_url      = module.sqs_queues.feedback_queue_url

  aws_region = var.aws_region

  tags = local.common_tags
}
