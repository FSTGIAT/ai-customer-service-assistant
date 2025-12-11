# Playground Environment Configuration
# AWS Playground for RAG Evaluation Infrastructure
# Using existing VPC-Playground and IAM roles to avoid permission issues

terraform {
  required_version = ">= 1.5.0"

  # Uncomment for remote state
  # backend "s3" {
  #   bucket         = "call-analytics-terraform-state"
  #   key            = "playground/rag-evaluation/terraform.tfstate"
  #   region         = "eu-west-1"
  #   encrypt        = true
  #   dynamodb_table = "terraform-locks"
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "call-analytics"
      Environment = "playground"
      ManagedBy   = "terraform"
      Component   = "rag-evaluation"
    }
  }
}

# Call the root module
module "rag_evaluation" {
  source = "../../"

  aws_region  = var.aws_region
  environment = "playground"

  # =========================================================================
  # USE EXISTING VPC (VPC-Playground)
  # =========================================================================
  use_existing_vpc            = true
  existing_vpc_id             = "vpc-033dee33ab0fd2c6c"
  existing_private_subnet_ids = ["subnet-01d91d927b08e38de", "subnet-05808eb7c58cc70fc"]  # priv-subnet-1a, priv-subnet-1b
  existing_public_subnet_ids  = ["subnet-06650cee3d9f9c06b", "subnet-0ddd91144930ef332"]  # pub-subnet-1a, pub-subnet-1b

  # =========================================================================
  # USE EXISTING IAM ROLES
  # =========================================================================
  use_existing_iam_roles               = true
  existing_ecs_instance_role_arn       = "arn:aws:iam::811287567672:role/ecsInstanceRole"
  existing_ecs_instance_profile_arn    = "arn:aws:iam::811287567672:instance-profile/ecsInstanceRole"
  existing_ecs_task_execution_role_arn = "arn:aws:iam::811287567672:role/ecsTaskExecutionRole"
  existing_ecs_task_role_arn           = "arn:aws:iam::811287567672:role/ecsTaskExecutionRole"  # Using same role

  # =========================================================================
  # VPC Configuration (not used when use_existing_vpc = true)
  # =========================================================================
  vpc_cidr           = "10.0.0.0/16"
  availability_zones = ["eu-west-1a", "eu-west-1b"]

  # =========================================================================
  # OpenSearch Configuration (cost-optimized for playground)
  # =========================================================================
  opensearch_instance_type   = "r5.large.search"
  opensearch_instance_count  = 2
  opensearch_ebs_volume_size = 100
  opensearch_master_user     = var.opensearch_master_user
  opensearch_master_password = var.opensearch_master_password

  # =========================================================================
  # Lambda-Based Evaluation (No ECS GPU needed - avoids IAM PassRole issues)
  # =========================================================================
  enable_ecs_gpu_cluster = false  # Use Lambda instead of ECS for evaluation

  # Use existing Lambda role to avoid IAM CreateRole permission requirement
  use_existing_lambda_role = true
  existing_lambda_role_arn = "arn:aws:iam::811287567672:role/amplify-login-lambda-0a515816"

  # ECS GPU Configuration (only used if enable_ecs_gpu_cluster = true)
  ecs_gpu_instance_type = "g4dn.xlarge"
  ecs_gpu_min_size      = 1
  ecs_gpu_max_size      = 2
  ecs_gpu_desired_size  = 1

  # =========================================================================
  # SQS Configuration
  # =========================================================================
  sqs_message_retention_seconds  = 345600  # 4 days
  sqs_visibility_timeout_seconds = 300     # 5 minutes
}
