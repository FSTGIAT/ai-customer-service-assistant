# Evaluation Service Module - ECS Task Definition and Service

# =============================================================================
# ECR REPOSITORY
# =============================================================================

resource "aws_ecr_repository" "evaluation_service" {
  name                 = "${var.name_prefix}/evaluation-service"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
  }

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-evaluation-service"
  })
}

resource "aws_ecr_lifecycle_policy" "evaluation_service" {
  repository = aws_ecr_repository.evaluation_service.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 10 images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}

# =============================================================================
# CLOUDWATCH LOG GROUP
# =============================================================================

resource "aws_cloudwatch_log_group" "evaluation_service" {
  name              = "/ecs/${var.name_prefix}-evaluation-service"
  retention_in_days = 30

  tags = var.tags
}

# =============================================================================
# ECS TASK DEFINITION
# =============================================================================

resource "aws_ecs_task_definition" "evaluation_service" {
  family                   = "${var.name_prefix}-evaluation-service"
  requires_compatibilities = ["EC2"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 2048
  execution_role_arn       = var.ecs_task_execution_role_arn
  task_role_arn            = var.ecs_task_role_arn

  container_definitions = jsonencode([
    {
      name      = "evaluation-service"
      image     = "${aws_ecr_repository.evaluation_service.repository_url}:latest"
      essential = true

      portMappings = [
        {
          containerPort = 5001
          hostPort      = 5001
          protocol      = "tcp"
        }
      ]

      environment = [
        { name = "AWS_REGION", value = var.aws_region },
        { name = "OPENSEARCH_URL", value = "https://${var.opensearch_endpoint}" },
        { name = "EVALUATION_QUEUE_URL", value = var.evaluation_queue_url },
        { name = "KEYPOINT_QUEUE_URL", value = var.keypoint_queue_url },
        { name = "FEEDBACK_QUEUE_URL", value = var.feedback_queue_url },
        { name = "LOG_LEVEL", value = "INFO" },
        { name = "ENVIRONMENT", value = var.tags["Environment"] }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.evaluation_service.name
          "awslogs-region"        = var.aws_region
          "awslogs-stream-prefix" = "ecs"
        }
      }

      healthCheck = {
        command     = ["CMD-SHELL", "curl -f http://localhost:5001/health || exit 1"]
        interval    = 30
        timeout     = 10
        retries     = 3
        startPeriod = 60
      }

      # GPU resource requirements (optional, for embedding generation)
      resourceRequirements = [
        {
          type  = "GPU"
          value = "1"
        }
      ]
    }
  ])

  tags = var.tags
}

# =============================================================================
# ECS SERVICE
# =============================================================================

resource "aws_ecs_service" "evaluation_service" {
  name            = "${var.name_prefix}-evaluation-service"
  cluster         = var.ecs_cluster_id
  task_definition = aws_ecs_task_definition.evaluation_service.arn
  desired_count   = 1
  launch_type     = "EC2"

  network_configuration {
    subnets         = var.subnet_ids
    security_groups = var.security_group_ids
  }

  deployment_maximum_percent         = 200
  deployment_minimum_healthy_percent = 50

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  tags = var.tags

  lifecycle {
    ignore_changes = [desired_count]
  }
}

# =============================================================================
# CLOUDWATCH DASHBOARD
# =============================================================================

resource "aws_cloudwatch_dashboard" "evaluation_metrics" {
  dashboard_name = "${var.name_prefix}-rag-evaluation"

  dashboard_body = jsonencode({
    widgets = [
      {
        type   = "metric"
        x      = 0
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "RAG Accuracy Metrics"
          region = var.aws_region
          metrics = [
            ["RAGEvaluation", "PrecisionAt10", { label = "Precision@10" }],
            ["RAGEvaluation", "RecallAt10", { label = "Recall@10" }],
            ["RAGEvaluation", "RecallAt100", { label = "Recall@100" }],
            ["RAGEvaluation", "MRR", { label = "MRR" }]
          ]
          period = 300
          stat   = "Average"
        }
      },
      {
        type   = "metric"
        x      = 12
        y      = 0
        width  = 12
        height = 6
        properties = {
          title  = "Query Latency"
          region = var.aws_region
          metrics = [
            ["RAGEvaluation", "QueryLatency", { stat = "p50", label = "p50" }],
            ["RAGEvaluation", "QueryLatency", { stat = "p95", label = "p95" }],
            ["RAGEvaluation", "QueryLatency", { stat = "p99", label = "p99" }]
          ]
          period = 300
        }
      },
      {
        type   = "metric"
        x      = 0
        y      = 6
        width  = 8
        height = 6
        properties = {
          title  = "User Feedback"
          region = var.aws_region
          metrics = [
            ["RAGEvaluation", "FeedbackPositive", { label = "Positive" }],
            ["RAGEvaluation", "FeedbackNegative", { label = "Negative" }]
          ]
          period = 3600
          stat   = "Sum"
        }
      },
      {
        type   = "metric"
        x      = 8
        y      = 6
        width  = 8
        height = 6
        properties = {
          title  = "Search Strategy Comparison"
          region = var.aws_region
          metrics = [
            ["RAGEvaluation", "HybridSearchAccuracy", { label = "Hybrid" }],
            ["RAGEvaluation", "VectorSearchAccuracy", { label = "Vector Only" }],
            ["RAGEvaluation", "BM25SearchAccuracy", { label = "BM25 Only" }]
          ]
          period = 3600
          stat   = "Average"
        }
      },
      {
        type   = "metric"
        x      = 16
        y      = 6
        width  = 8
        height = 6
        properties = {
          title  = "Query Volume"
          region = var.aws_region
          metrics = [
            ["RAGEvaluation", "QueryCount", { label = "Total Queries" }],
            ["RAGEvaluation", "ZeroResultQueries", { label = "Zero Results" }]
          ]
          period = 300
          stat   = "Sum"
        }
      }
    ]
  })
}
