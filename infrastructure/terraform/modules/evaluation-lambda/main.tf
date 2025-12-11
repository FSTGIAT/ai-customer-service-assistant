# Lambda-based RAG Evaluation Module
# Triggered by SQS, queries OpenSearch, publishes metrics to CloudWatch

# =============================================================================
# IAM ROLE FOR LAMBDA (use existing or create new)
# =============================================================================

locals {
  # Use existing role if provided, otherwise create new one
  lambda_role_arn = var.use_existing_lambda_role ? var.existing_lambda_role_arn : aws_iam_role.evaluation_lambda[0].arn
}

resource "aws_iam_role" "evaluation_lambda" {
  count = var.use_existing_lambda_role ? 0 : 1

  name = "${var.name_prefix}-evaluation-lambda-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })

  tags = var.tags
}

# Basic Lambda execution policy (only if creating new role)
resource "aws_iam_role_policy_attachment" "lambda_basic" {
  count      = var.use_existing_lambda_role ? 0 : 1
  role       = aws_iam_role.evaluation_lambda[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# VPC access for Lambda (only if creating new role)
resource "aws_iam_role_policy_attachment" "lambda_vpc" {
  count      = var.use_existing_lambda_role ? 0 : 1
  role       = aws_iam_role.evaluation_lambda[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

# Custom policy for SQS, OpenSearch, CloudWatch (only if creating new role)
resource "aws_iam_role_policy" "evaluation_lambda_policy" {
  count = var.use_existing_lambda_role ? 0 : 1

  name = "${var.name_prefix}-evaluation-lambda-policy"
  role = aws_iam_role.evaluation_lambda[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "SQSAccess"
        Effect = "Allow"
        Action = [
          "sqs:ReceiveMessage",
          "sqs:DeleteMessage",
          "sqs:GetQueueAttributes",
          "sqs:SendMessage"
        ]
        Resource = var.sqs_queue_arns
      },
      {
        Sid    = "OpenSearchAccess"
        Effect = "Allow"
        Action = [
          "es:ESHttpGet",
          "es:ESHttpPost",
          "es:ESHttpPut",
          "es:ESHttpHead"
        ]
        Resource = "${var.opensearch_arn}/*"
      },
      {
        Sid    = "CloudWatchMetrics"
        Effect = "Allow"
        Action = [
          "cloudwatch:PutMetricData"
        ]
        Resource = "*"
      }
    ]
  })
}

# =============================================================================
# LAMBDA FUNCTION
# =============================================================================

resource "aws_lambda_function" "evaluation" {
  function_name = "${var.name_prefix}-rag-evaluation"
  role          = local.lambda_role_arn
  handler       = "evaluation.handler"
  runtime       = "python3.11"
  timeout       = 300  # 5 minutes
  memory_size   = 1024

  filename         = data.archive_file.lambda_zip.output_path
  source_code_hash = data.archive_file.lambda_zip.output_base64sha256

  vpc_config {
    subnet_ids         = var.subnet_ids
    security_group_ids = var.security_group_ids
  }

  environment {
    variables = {
      OPENSEARCH_ENDPOINT  = var.opensearch_endpoint
      OPENSEARCH_USER      = var.opensearch_user
      OPENSEARCH_PASSWORD  = var.opensearch_password
      ENVIRONMENT          = var.tags["Environment"]
      FEEDBACK_QUEUE_URL   = var.feedback_queue_url
    }
  }

  tags = var.tags
}

# Package Lambda code
data "archive_file" "lambda_zip" {
  type        = "zip"
  source_dir  = "${path.module}/src"
  output_path = "${path.module}/lambda.zip"
}

# =============================================================================
# SQS TRIGGERS
# =============================================================================

# Evaluation queue trigger
resource "aws_lambda_event_source_mapping" "evaluation_queue" {
  event_source_arn = var.evaluation_queue_arn
  function_name    = aws_lambda_function.evaluation.arn
  batch_size       = 10
  enabled          = true

  scaling_config {
    maximum_concurrency = 10
  }
}

# Feedback queue trigger
resource "aws_lambda_event_source_mapping" "feedback_queue" {
  event_source_arn = var.feedback_queue_arn
  function_name    = aws_lambda_function.evaluation.arn
  batch_size       = 10
  enabled          = true
}

# =============================================================================
# CLOUDWATCH LOG GROUP
# =============================================================================

resource "aws_cloudwatch_log_group" "evaluation_lambda" {
  name              = "/aws/lambda/${var.name_prefix}-rag-evaluation"
  retention_in_days = 30

  tags = var.tags
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
          title  = "Query Latency (ms)"
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
          title  = "Lambda Invocations"
          region = var.aws_region
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", "${var.name_prefix}-rag-evaluation"],
            ["AWS/Lambda", "Errors", "FunctionName", "${var.name_prefix}-rag-evaluation"],
            ["AWS/Lambda", "Throttles", "FunctionName", "${var.name_prefix}-rag-evaluation"]
          ]
          period = 300
          stat   = "Sum"
        }
      },
      {
        type   = "metric"
        x      = 16
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
      }
    ]
  })
}
