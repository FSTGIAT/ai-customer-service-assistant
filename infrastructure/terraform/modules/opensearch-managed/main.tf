# AWS Managed OpenSearch Service Module
# Hybrid Search (BM25 + kNN) enabled with SLA

# =============================================================================
# OPENSEARCH DOMAIN
# =============================================================================

resource "aws_opensearch_domain" "main" {
  domain_name    = var.domain_name
  engine_version = var.engine_version

  cluster_config {
    instance_type          = var.instance_type
    instance_count         = var.instance_count
    zone_awareness_enabled = var.instance_count > 1

    dynamic "zone_awareness_config" {
      for_each = var.instance_count > 1 ? [1] : []
      content {
        availability_zone_count = min(var.instance_count, 2)
      }
    }

    # Dedicated master nodes for production
    dedicated_master_enabled = var.dedicated_master_enabled
    dedicated_master_type    = var.dedicated_master_enabled ? var.dedicated_master_type : null
    dedicated_master_count   = var.dedicated_master_enabled ? var.dedicated_master_count : null
  }

  # VPC Configuration (private access only)
  vpc_options {
    subnet_ids         = slice(var.subnet_ids, 0, min(length(var.subnet_ids), var.instance_count))
    security_group_ids = var.security_group_ids
  }

  # EBS Storage
  ebs_options {
    ebs_enabled = true
    volume_size = var.ebs_volume_size
    volume_type = "gp3"
    iops        = 3000
    throughput  = 125
  }

  # Encryption
  encrypt_at_rest {
    enabled = true
  }

  node_to_node_encryption {
    enabled = true
  }

  # Domain endpoint options
  domain_endpoint_options {
    enforce_https       = true
    tls_security_policy = "Policy-Min-TLS-1-2-2019-07"
  }

  # Advanced options for hybrid search
  advanced_options = {
    "rest.action.multi.allow_explicit_index" = "true"
    "indices.query.bool.max_clause_count"    = "10000"
  }

  # Logging
  log_publishing_options {
    cloudwatch_log_group_arn = aws_cloudwatch_log_group.opensearch_logs.arn
    log_type                 = "INDEX_SLOW_LOGS"
  }

  log_publishing_options {
    cloudwatch_log_group_arn = aws_cloudwatch_log_group.opensearch_logs.arn
    log_type                 = "SEARCH_SLOW_LOGS"
  }

  log_publishing_options {
    cloudwatch_log_group_arn = aws_cloudwatch_log_group.opensearch_error_logs.arn
    log_type                 = "ES_APPLICATION_LOGS"
  }

  # Fine-grained access control
  advanced_security_options {
    enabled                        = true
    internal_user_database_enabled = true

    master_user_options {
      master_user_name     = var.master_user_name
      master_user_password = var.master_user_password
    }
  }

  # Auto-tune for performance optimization
  auto_tune_options {
    desired_state       = "ENABLED"
    rollback_on_disable = "NO_ROLLBACK"
  }

  tags = merge(var.tags, {
    Name = var.domain_name
  })
}

# =============================================================================
# CLOUDWATCH LOG GROUPS
# =============================================================================

resource "aws_cloudwatch_log_group" "opensearch_logs" {
  name              = "/aws/opensearch/${var.domain_name}/slow-logs"
  retention_in_days = 30

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "opensearch_error_logs" {
  name              = "/aws/opensearch/${var.domain_name}/error-logs"
  retention_in_days = 30

  tags = var.tags
}

# Log group resource policy for OpenSearch
resource "aws_cloudwatch_log_resource_policy" "opensearch_logs" {
  policy_name = "${var.domain_name}-logs-policy"

  policy_document = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          Service = "es.amazonaws.com"
        }
        Action = [
          "logs:PutLogEvents",
          "logs:CreateLogStream"
        ]
        Resource = [
          "${aws_cloudwatch_log_group.opensearch_logs.arn}:*",
          "${aws_cloudwatch_log_group.opensearch_error_logs.arn}:*"
        ]
      }
    ]
  })
}

# =============================================================================
# ACCESS POLICY (only for non-VPC domains, VPC uses security groups)
# =============================================================================

# For VPC-based domains, access is controlled via security groups
# IP-based policies are not allowed for VPC endpoints
# This policy is only created for public (non-VPC) domains
resource "aws_opensearch_domain_policy" "main" {
  count = length(var.subnet_ids) == 0 ? 1 : 0  # Only create for non-VPC domains

  domain_name = aws_opensearch_domain.main.domain_name

  access_policies = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Principal = {
          AWS = "*"
        }
        Action   = "es:*"
        Resource = "${aws_opensearch_domain.main.arn}/*"
        Condition = {
          IpAddress = {
            "aws:SourceIp" = var.allowed_cidr_blocks
          }
        }
      }
    ]
  })
}

# =============================================================================
# INDEX TEMPLATES (via null_resource provisioner)
# =============================================================================

# Create index templates after domain is available
resource "null_resource" "create_index_templates" {
  depends_on = [aws_opensearch_domain.main]

  triggers = {
    domain_endpoint = aws_opensearch_domain.main.endpoint
  }

  provisioner "local-exec" {
    command = <<-EOF
      # Wait for domain to be ready
      sleep 60

      # Create hybrid search pipeline
      curl -X PUT "https://${aws_opensearch_domain.main.endpoint}/_search/pipeline/hybrid-search-pipeline" \
        -u "${var.master_user_name}:${var.master_user_password}" \
        -H "Content-Type: application/json" \
        -d '{
          "description": "Post processor for hybrid search normalization",
          "phase_results_processors": [
            {
              "normalization-processor": {
                "normalization": {
                  "technique": "min_max"
                },
                "combination": {
                  "technique": "arithmetic_mean",
                  "parameters": {
                    "weights": [0.7, 0.3]
                  }
                }
              }
            }
          ]
        }' || true

      # Create call-keypoints index template
      curl -X PUT "https://${aws_opensearch_domain.main.endpoint}/_index_template/call-keypoints-template" \
        -u "${var.master_user_name}:${var.master_user_password}" \
        -H "Content-Type: application/json" \
        -d @${path.module}/templates/call-keypoints-template.json || true

      # Create rag-evaluations index template
      curl -X PUT "https://${aws_opensearch_domain.main.endpoint}/_index_template/rag-evaluations-template" \
        -u "${var.master_user_name}:${var.master_user_password}" \
        -H "Content-Type: application/json" \
        -d @${path.module}/templates/rag-evaluations-template.json || true

      # Create call-summaries index template with embeddings
      curl -X PUT "https://${aws_opensearch_domain.main.endpoint}/_index_template/call-summaries-template" \
        -u "${var.master_user_name}:${var.master_user_password}" \
        -H "Content-Type: application/json" \
        -d @${path.module}/templates/call-summaries-template.json || true
    EOF
  }
}
