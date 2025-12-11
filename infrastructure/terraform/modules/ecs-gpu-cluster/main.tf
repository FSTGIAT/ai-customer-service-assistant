# ECS GPU Cluster Module - EC2 instances with NVIDIA GPU support

data "aws_region" "current" {}

# =============================================================================
# ECS CLUSTER
# =============================================================================

resource "aws_ecs_cluster" "main" {
  name = "${var.name_prefix}-gpu-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }

  configuration {
    execute_command_configuration {
      logging = "OVERRIDE"

      log_configuration {
        cloud_watch_log_group_name = aws_cloudwatch_log_group.ecs_exec.name
      }
    }
  }

  tags = merge(var.tags, {
    Name = "${var.name_prefix}-gpu-cluster"
  })
}

resource "aws_cloudwatch_log_group" "ecs_exec" {
  name              = "/ecs/${var.name_prefix}/exec-logs"
  retention_in_days = 30

  tags = var.tags
}

# =============================================================================
# ECS CAPACITY PROVIDER (Auto Scaling Group)
# =============================================================================

resource "aws_ecs_cluster_capacity_providers" "main" {
  cluster_name = aws_ecs_cluster.main.name

  capacity_providers = [aws_ecs_capacity_provider.gpu.name]

  default_capacity_provider_strategy {
    base              = 1
    weight            = 100
    capacity_provider = aws_ecs_capacity_provider.gpu.name
  }
}

resource "aws_ecs_capacity_provider" "gpu" {
  name = "${var.name_prefix}-gpu-capacity-provider"

  auto_scaling_group_provider {
    auto_scaling_group_arn         = aws_autoscaling_group.ecs_gpu.arn
    managed_termination_protection = "DISABLED"

    managed_scaling {
      maximum_scaling_step_size = 2
      minimum_scaling_step_size = 1
      status                    = "ENABLED"
      target_capacity           = 100
    }
  }

  tags = var.tags
}

# =============================================================================
# LAUNCH TEMPLATE (GPU-optimized AMI with NVIDIA drivers)
# =============================================================================

data "aws_ami" "ecs_gpu_optimized" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["amzn2-ami-ecs-gpu-hvm-*-x86_64-ebs"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

locals {
  # Use provided instance profile ARN or derive from role ARN
  instance_profile_arn = var.ecs_instance_profile_arn != "" ? var.ecs_instance_profile_arn : var.ecs_instance_role_arn
}

resource "aws_launch_template" "ecs_gpu" {
  name          = "${var.name_prefix}-ecs-gpu-launch-template"
  image_id      = data.aws_ami.ecs_gpu_optimized.id
  instance_type = var.instance_type

  iam_instance_profile {
    arn = local.instance_profile_arn
  }

  network_interfaces {
    associate_public_ip_address = false
    security_groups             = var.security_group_ids
    delete_on_termination       = true
  }

  # ECS agent configuration
  user_data = base64encode(<<-EOF
    #!/bin/bash
    echo "ECS_CLUSTER=${aws_ecs_cluster.main.name}" >> /etc/ecs/ecs.config
    echo "ECS_ENABLE_GPU_SUPPORT=true" >> /etc/ecs/ecs.config
    echo "ECS_NVIDIA_RUNTIME=nvidia" >> /etc/ecs/ecs.config
    echo "ECS_ENABLE_CONTAINER_METADATA=true" >> /etc/ecs/ecs.config
    echo "ECS_ENABLE_SPOT_INSTANCE_DRAINING=true" >> /etc/ecs/ecs.config
    echo "ECS_CONTAINER_STOP_TIMEOUT=120s" >> /etc/ecs/ecs.config

    # Configure NVIDIA MPS for GPU sharing
    nvidia-smi -pm 1
    nvidia-cuda-mps-control -d

    # Verify NVIDIA drivers
    nvidia-smi

    # Start ECS agent
    systemctl enable --now ecs
  EOF
  )

  # EBS configuration
  block_device_mappings {
    device_name = "/dev/xvda"

    ebs {
      volume_size           = 100
      volume_type           = "gp3"
      delete_on_termination = true
      encrypted             = true
    }
  }

  # Instance metadata options
  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  monitoring {
    enabled = true
  }

  tag_specifications {
    resource_type = "instance"

    tags = merge(var.tags, {
      Name = "${var.name_prefix}-ecs-gpu-instance"
    })
  }

  tag_specifications {
    resource_type = "volume"

    tags = merge(var.tags, {
      Name = "${var.name_prefix}-ecs-gpu-volume"
    })
  }

  tags = var.tags
}

# =============================================================================
# AUTO SCALING GROUP
# =============================================================================

resource "aws_autoscaling_group" "ecs_gpu" {
  name                = "${var.name_prefix}-ecs-gpu-asg"
  vpc_zone_identifier = var.subnet_ids
  min_size            = var.min_size
  max_size            = var.max_size
  desired_capacity    = var.desired_size

  launch_template {
    id      = aws_launch_template.ecs_gpu.id
    version = "$Latest"
  }

  # Protect from scale-in during task execution
  protect_from_scale_in = false

  # Health check
  health_check_type         = "EC2"
  health_check_grace_period = 300

  # Instance refresh for updates
  instance_refresh {
    strategy = "Rolling"
    preferences {
      min_healthy_percentage = 50
    }
  }

  tag {
    key                 = "Name"
    value               = "${var.name_prefix}-ecs-gpu-instance"
    propagate_at_launch = true
  }

  tag {
    key                 = "AmazonECSManaged"
    value               = "true"
    propagate_at_launch = true
  }

  dynamic "tag" {
    for_each = var.tags

    content {
      key                 = tag.key
      value               = tag.value
      propagate_at_launch = true
    }
  }

  lifecycle {
    create_before_destroy = true
  }
}

# =============================================================================
# CLOUDWATCH ALARMS
# =============================================================================

resource "aws_cloudwatch_metric_alarm" "gpu_utilization_high" {
  alarm_name          = "${var.name_prefix}-gpu-utilization-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "GPUUtilization"
  namespace           = "AWS/ECS"
  period              = 300
  statistic           = "Average"
  threshold           = 80
  alarm_description   = "GPU utilization is high, consider scaling up"

  dimensions = {
    ClusterName = aws_ecs_cluster.main.name
  }

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "memory_utilization_high" {
  alarm_name          = "${var.name_prefix}-memory-utilization-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "MemoryUtilization"
  namespace           = "AWS/ECS"
  period              = 300
  statistic           = "Average"
  threshold           = 85
  alarm_description   = "Memory utilization is high"

  dimensions = {
    ClusterName = aws_ecs_cluster.main.name
  }

  tags = var.tags
}
