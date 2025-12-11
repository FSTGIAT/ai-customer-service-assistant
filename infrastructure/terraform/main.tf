# Main Terraform configuration for RAG Evaluation Infrastructure
# Supports using existing VPC and IAM roles or creating new ones

locals {
  name_prefix = "${var.project_name}-${var.environment}"

  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }

  # Use existing or created resources
  vpc_id             = var.use_existing_vpc ? var.existing_vpc_id : module.networking[0].vpc_id
  private_subnet_ids = var.use_existing_vpc ? var.existing_private_subnet_ids : module.networking[0].private_subnet_ids
  public_subnet_ids  = var.use_existing_vpc ? var.existing_public_subnet_ids : module.networking[0].public_subnet_ids

  ecs_instance_role_arn       = var.use_existing_iam_roles ? var.existing_ecs_instance_role_arn : module.iam_policies[0].ecs_instance_role_arn
  ecs_task_execution_role_arn = var.use_existing_iam_roles ? var.existing_ecs_task_execution_role_arn : module.iam_policies[0].ecs_task_execution_role_arn
  ecs_task_role_arn           = var.use_existing_iam_roles ? (var.existing_ecs_task_role_arn != "" ? var.existing_ecs_task_role_arn : var.existing_ecs_task_execution_role_arn) : module.iam_policies[0].ecs_task_role_arn
}

# =============================================================================
# NETWORKING (conditionally created)
# =============================================================================

module "networking" {
  source = "./modules/networking"
  count  = var.use_existing_vpc ? 0 : 1

  name_prefix        = local.name_prefix
  vpc_cidr           = var.vpc_cidr
  availability_zones = var.availability_zones

  tags = local.common_tags
}

# Security groups for existing VPC
resource "aws_security_group" "ecs" {
  count = var.use_existing_vpc ? 1 : 0

  name        = "${local.name_prefix}-ecs-sg"
  description = "Security group for ECS tasks"
  vpc_id      = local.vpc_id

  ingress {
    description = "Allow internal traffic"
    from_port   = 0
    to_port     = 65535
    protocol    = "tcp"
    self        = true
  }

  ingress {
    description = "Allow HTTP"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  ingress {
    description = "Allow HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  ingress {
    description = "Allow Flask app port"
    from_port   = 5000
    to_port     = 5000
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-ecs-sg"
  })
}

resource "aws_security_group" "opensearch" {
  count = var.use_existing_vpc ? 1 : 0

  name        = "${local.name_prefix}-opensearch-sg"
  description = "Security group for OpenSearch domain"
  vpc_id      = local.vpc_id

  ingress {
    description = "Allow HTTPS from VPC"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["10.0.0.0/16"]
  }

  egress {
    description = "Allow all outbound"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, {
    Name = "${local.name_prefix}-opensearch-sg"
  })
}

locals {
  ecs_security_group_id        = var.use_existing_vpc ? aws_security_group.ecs[0].id : module.networking[0].ecs_security_group_id
  opensearch_security_group_id = var.use_existing_vpc ? aws_security_group.opensearch[0].id : module.networking[0].opensearch_security_group_id
}

# =============================================================================
# IAM POLICIES (conditionally created)
# =============================================================================

module "iam_policies" {
  source = "./modules/iam-policies"
  count  = var.use_existing_iam_roles ? 0 : 1

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
  domain_name           = "ca-${var.environment}-search"  # Shortened to fit 28-char limit
  engine_version        = var.opensearch_version
  instance_type         = var.opensearch_instance_type
  instance_count        = var.opensearch_instance_count
  ebs_volume_size       = var.opensearch_ebs_volume_size

  vpc_id             = local.vpc_id
  subnet_ids         = local.private_subnet_ids
  security_group_ids = [local.opensearch_security_group_id]

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
# ECS GPU CLUSTER (Optional - for future GPU workloads)
# =============================================================================

module "ecs_gpu_cluster" {
  source = "./modules/ecs-gpu-cluster"
  count  = var.enable_ecs_gpu_cluster ? 1 : 0

  name_prefix        = local.name_prefix
  vpc_id             = local.vpc_id
  subnet_ids         = local.private_subnet_ids
  security_group_ids = [local.ecs_security_group_id]

  instance_type = var.ecs_gpu_instance_type
  min_size      = var.ecs_gpu_min_size
  max_size      = var.ecs_gpu_max_size
  desired_size  = var.ecs_gpu_desired_size

  ecs_instance_role_arn       = local.ecs_instance_role_arn
  ecs_instance_profile_arn    = var.use_existing_iam_roles ? var.existing_ecs_instance_profile_arn : ""
  ecs_task_execution_role_arn = local.ecs_task_execution_role_arn
  ecs_task_role_arn           = local.ecs_task_role_arn

  tags = local.common_tags
}

# =============================================================================
# LAMBDA-BASED EVALUATION SERVICE (Serverless - No IAM PassRole needed)
# =============================================================================

module "evaluation_lambda" {
  source = "./modules/evaluation-lambda"

  name_prefix = local.name_prefix
  aws_region  = var.aws_region

  subnet_ids         = local.private_subnet_ids
  security_group_ids = [local.ecs_security_group_id]

  opensearch_endpoint  = module.opensearch.domain_endpoint
  opensearch_arn       = module.opensearch.domain_arn
  opensearch_user      = var.opensearch_master_user
  opensearch_password  = var.opensearch_master_password

  evaluation_queue_arn = module.sqs_queues.evaluation_queue_arn
  feedback_queue_arn   = module.sqs_queues.feedback_queue_arn
  feedback_queue_url   = module.sqs_queues.feedback_queue_url

  sqs_queue_arns = [
    module.sqs_queues.evaluation_queue_arn,
    module.sqs_queues.feedback_queue_arn,
    module.sqs_queues.keypoint_queue_arn
  ]

  # Use existing Lambda role to avoid IAM CreateRole permission requirement
  use_existing_lambda_role = var.use_existing_lambda_role
  existing_lambda_role_arn = var.existing_lambda_role_arn

  tags = local.common_tags
}
