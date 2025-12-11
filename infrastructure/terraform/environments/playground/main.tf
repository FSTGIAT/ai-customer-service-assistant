# Playground Environment Configuration
# AWS Playground for RAG Evaluation Infrastructure

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

  # VPC Configuration
  vpc_cidr           = "10.0.0.0/16"
  availability_zones = ["eu-west-1a", "eu-west-1b"]

  # OpenSearch Configuration (cost-optimized for playground)
  opensearch_instance_type   = "r5.large.search"
  opensearch_instance_count  = 2
  opensearch_ebs_volume_size = 100

  # ECS GPU Configuration
  ecs_gpu_instance_type = "g4dn.xlarge"
  ecs_gpu_min_size      = 1
  ecs_gpu_max_size      = 2
  ecs_gpu_desired_size  = 1

  # SQS Configuration
  sqs_message_retention_seconds  = 345600  # 4 days
  sqs_visibility_timeout_seconds = 300     # 5 minutes
}
