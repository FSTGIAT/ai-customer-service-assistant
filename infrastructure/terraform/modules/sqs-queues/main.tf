# SQS Queues Module for RAG Evaluation Pipeline

# =============================================================================
# KEYPOINT PIPELINE QUEUE
# =============================================================================

resource "aws_sqs_queue" "keypoint" {
  name                       = "${var.name_prefix}-keypoint-pipe-queue"
  visibility_timeout_seconds = var.visibility_timeout_seconds
  message_retention_seconds  = var.message_retention_seconds
  receive_wait_time_seconds  = 20  # Long polling

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.keypoint_dlq.arn
    maxReceiveCount     = 3
  })

  tags = merge(var.tags, {
    Name    = "${var.name_prefix}-keypoint-pipe-queue"
    Purpose = "Keypoint extraction and embedding pipeline"
  })
}

resource "aws_sqs_queue" "keypoint_dlq" {
  name                      = "${var.name_prefix}-keypoint-pipe-dlq"
  message_retention_seconds = 1209600  # 14 days

  tags = merge(var.tags, {
    Name    = "${var.name_prefix}-keypoint-pipe-dlq"
    Purpose = "Dead letter queue for keypoint pipeline"
  })
}

# =============================================================================
# EVALUATION PIPELINE QUEUE
# =============================================================================

resource "aws_sqs_queue" "evaluation" {
  name                       = "${var.name_prefix}-evaluation-pipe-queue"
  visibility_timeout_seconds = var.visibility_timeout_seconds
  message_retention_seconds  = var.message_retention_seconds
  receive_wait_time_seconds  = 20

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.evaluation_dlq.arn
    maxReceiveCount     = 3
  })

  tags = merge(var.tags, {
    Name    = "${var.name_prefix}-evaluation-pipe-queue"
    Purpose = "RAG evaluation metrics pipeline"
  })
}

resource "aws_sqs_queue" "evaluation_dlq" {
  name                      = "${var.name_prefix}-evaluation-pipe-dlq"
  message_retention_seconds = 1209600

  tags = merge(var.tags, {
    Name    = "${var.name_prefix}-evaluation-pipe-dlq"
    Purpose = "Dead letter queue for evaluation pipeline"
  })
}

# =============================================================================
# FEEDBACK PIPELINE QUEUE
# =============================================================================

resource "aws_sqs_queue" "feedback" {
  name                       = "${var.name_prefix}-feedback-pipe-queue"
  visibility_timeout_seconds = 30  # Shorter timeout for feedback
  message_retention_seconds  = var.message_retention_seconds
  receive_wait_time_seconds  = 20

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.feedback_dlq.arn
    maxReceiveCount     = 3
  })

  tags = merge(var.tags, {
    Name    = "${var.name_prefix}-feedback-pipe-queue"
    Purpose = "User feedback collection pipeline"
  })
}

resource "aws_sqs_queue" "feedback_dlq" {
  name                      = "${var.name_prefix}-feedback-pipe-dlq"
  message_retention_seconds = 1209600

  tags = merge(var.tags, {
    Name    = "${var.name_prefix}-feedback-pipe-dlq"
    Purpose = "Dead letter queue for feedback pipeline"
  })
}

# =============================================================================
# CLOUDWATCH ALARMS FOR DLQ MONITORING
# =============================================================================

resource "aws_cloudwatch_metric_alarm" "keypoint_dlq_alarm" {
  alarm_name          = "${var.name_prefix}-keypoint-dlq-messages"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "Alarm when messages land in keypoint DLQ"

  dimensions = {
    QueueName = aws_sqs_queue.keypoint_dlq.name
  }

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "evaluation_dlq_alarm" {
  alarm_name          = "${var.name_prefix}-evaluation-dlq-messages"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 1
  metric_name         = "ApproximateNumberOfMessagesVisible"
  namespace           = "AWS/SQS"
  period              = 300
  statistic           = "Sum"
  threshold           = 0
  alarm_description   = "Alarm when messages land in evaluation DLQ"

  dimensions = {
    QueueName = aws_sqs_queue.evaluation_dlq.name
  }

  tags = var.tags
}
