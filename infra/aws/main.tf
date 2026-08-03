locals {
  enable_route53 = var.route53_zone_id != null && var.domain_name != null
  enable_budget  = length(var.budget_notification_emails) > 0
  public_ipv4    = var.ip_address_type == "dualstack" ? ["0.0.0.0/0"] : []
  public_ipv6    = ["::/0"]
}

resource "terraform_data" "input_validation" {
  input = var.project_name

  lifecycle {
    precondition {
      condition     = startswith(var.availability_zone, var.aws_region)
      error_message = "availability_zone must belong to aws_region."
    }

    precondition {
      condition     = (var.route53_zone_id == null) == (var.domain_name == null)
      error_message = "route53_zone_id and domain_name must be supplied together."
    }
  }
}

resource "aws_lightsail_instance" "app" {
  name              = "${var.project_name}-app"
  availability_zone = var.availability_zone
  blueprint_id      = var.lightsail_blueprint_id
  bundle_id         = var.lightsail_bundle_id
  key_pair_name     = var.lightsail_key_pair_name
  ip_address_type   = var.ip_address_type
}

resource "aws_lightsail_static_ip" "app" {
  count = var.ip_address_type == "dualstack" ? 1 : 0
  name  = "${var.project_name}-ipv4"
}

resource "aws_lightsail_static_ip_attachment" "app" {
  count          = var.ip_address_type == "dualstack" ? 1 : 0
  static_ip_name = aws_lightsail_static_ip.app[0].name
  instance_name  = aws_lightsail_instance.app.name
}

resource "aws_lightsail_instance_public_ports" "app" {
  instance_name = aws_lightsail_instance.app.name

  port_info {
    protocol   = "tcp"
    from_port  = var.ssh_port
    to_port    = var.ssh_port
    cidrs      = var.ssh_ipv4_cidrs
    ipv6_cidrs = var.ssh_ipv6_cidrs
  }

  port_info {
    protocol   = "tcp"
    from_port  = 80
    to_port    = 80
    cidrs      = local.public_ipv4
    ipv6_cidrs = local.public_ipv6
  }

  port_info {
    protocol   = "tcp"
    from_port  = 443
    to_port    = 443
    cidrs      = local.public_ipv4
    ipv6_cidrs = local.public_ipv6
  }

  lifecycle {
    precondition {
      condition = (
        length(var.ssh_ipv4_cidrs) > 0 ||
        length(var.ssh_ipv6_cidrs) > 0
      )
      error_message = "At least one restricted SSH source CIDR is required."
    }
  }
}

resource "aws_s3_bucket" "backup" {
  bucket        = var.backup_bucket_name
  force_destroy = false

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_ownership_controls" "backup" {
  bucket = aws_s3_bucket.backup.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "backup" {
  bucket = aws_s3_bucket.backup.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "backup" {
  bucket = aws_s3_bucket.backup.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "backup" {
  bucket = aws_s3_bucket.backup.id

  rule {
    id     = "abort-incomplete-multipart-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

resource "aws_iam_user" "backup" {
  name = var.backup_user_name

  lifecycle {
    prevent_destroy = true
  }
}

data "aws_iam_policy_document" "backup" {
  statement {
    sid = "ResticBucketMetadata"

    actions = [
      "s3:GetBucketLocation",
      "s3:ListBucket",
    ]

    resources = [aws_s3_bucket.backup.arn]
  }

  statement {
    sid = "ResticRepositoryObjects"

    actions = [
      "s3:DeleteObject",
      "s3:GetObject",
      "s3:PutObject",
    ]

    resources = ["${aws_s3_bucket.backup.arn}/*"]
  }
}

resource "aws_iam_user_policy" "backup" {
  name   = "${var.project_name}-restic"
  user   = aws_iam_user.backup.name
  policy = data.aws_iam_policy_document.backup.json
}

resource "aws_route53_record" "app_ipv4" {
  count = local.enable_route53 && var.ip_address_type == "dualstack" ? 1 : 0

  zone_id = var.route53_zone_id
  name    = var.domain_name
  type    = "A"
  ttl     = 300
  records = [aws_lightsail_static_ip.app[0].ip_address]
}

resource "aws_budgets_budget" "monthly" {
  count = local.enable_budget ? 1 : 0

  name         = var.budget_name
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    notification_type          = "ACTUAL"
    threshold                  = 50
    threshold_type             = "PERCENTAGE"
    subscriber_email_addresses = var.budget_notification_emails
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    notification_type          = "ACTUAL"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    subscriber_email_addresses = var.budget_notification_emails
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    notification_type          = "ACTUAL"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    subscriber_email_addresses = var.budget_notification_emails
  }

  notification {
    comparison_operator        = "GREATER_THAN"
    notification_type          = "FORECASTED"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    subscriber_email_addresses = var.budget_notification_emails
  }

}
