output "keypoint_queue_url" {
  description = "URL of the keypoint pipeline queue"
  value       = aws_sqs_queue.keypoint.url
}

output "keypoint_queue_arn" {
  description = "ARN of the keypoint pipeline queue"
  value       = aws_sqs_queue.keypoint.arn
}

output "evaluation_queue_url" {
  description = "URL of the evaluation pipeline queue"
  value       = aws_sqs_queue.evaluation.url
}

output "evaluation_queue_arn" {
  description = "ARN of the evaluation pipeline queue"
  value       = aws_sqs_queue.evaluation.arn
}

output "feedback_queue_url" {
  description = "URL of the feedback pipeline queue"
  value       = aws_sqs_queue.feedback.url
}

output "feedback_queue_arn" {
  description = "ARN of the feedback pipeline queue"
  value       = aws_sqs_queue.feedback.arn
}

output "all_queue_arns" {
  description = "List of all queue ARNs for IAM policies"
  value = [
    aws_sqs_queue.keypoint.arn,
    aws_sqs_queue.keypoint_dlq.arn,
    aws_sqs_queue.evaluation.arn,
    aws_sqs_queue.evaluation_dlq.arn,
    aws_sqs_queue.feedback.arn,
    aws_sqs_queue.feedback_dlq.arn
  ]
}
