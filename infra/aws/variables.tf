variable "aws_region" {
  description = "AWS region for Lightsail, S3, IAM policy construction, and optional DNS records."
  type        = string
}

variable "availability_zone" {
  description = "Lightsail availability zone, which must belong to aws_region."
  type        = string
}

variable "project_name" {
  description = "Short deployment-specific prefix used in resource names."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,31}$", var.project_name))
    error_message = "project_name must be 3-32 lowercase letters, digits, or hyphens and start with a letter."
  }
}

variable "lightsail_blueprint_id" {
  description = "Current Ubuntu LTS blueprint ID returned by aws lightsail get-blueprints."
  type        = string
}

variable "lightsail_bundle_id" {
  description = "Lightsail bundle ID sized for the application."
  type        = string
}

variable "lightsail_key_pair_name" {
  description = "Optional existing Lightsail key-pair name. Leave null to use the account default."
  type        = string
  default     = null
  nullable    = true
}

variable "ip_address_type" {
  description = "Lightsail networking mode."
  type        = string
  default     = "dualstack"

  validation {
    condition     = contains(["dualstack", "ipv6"], var.ip_address_type)
    error_message = "ip_address_type must be dualstack or ipv6."
  }
}

variable "ssh_port" {
  description = "Restricted SSH administration port."
  type        = number
  default     = 22

  validation {
    condition     = var.ssh_port >= 1 && var.ssh_port <= 65535
    error_message = "ssh_port must be between 1 and 65535."
  }
}

variable "ssh_ipv4_cidrs" {
  description = "Operator IPv4 CIDRs allowed to reach SSH. Prefer one current /32."
  type        = set(string)
  default     = []
}

variable "ssh_ipv6_cidrs" {
  description = "Operator IPv6 CIDRs allowed to reach SSH. Prefer one current /128."
  type        = set(string)
  default     = []
}

variable "backup_bucket_name" {
  description = "Globally unique private S3 bucket name for the encrypted restic repository."
  type        = string
}

variable "backup_user_name" {
  description = "IAM user name for the least-privilege backup identity. Access keys are deliberately not managed here."
  type        = string
}

variable "route53_zone_id" {
  description = "Optional Route 53 hosted zone ID. Null leaves DNS with the selected external provider."
  type        = string
  default     = null
  nullable    = true
}

variable "domain_name" {
  description = "Optional fully qualified application hostname. Required with route53_zone_id."
  type        = string
  default     = null
  nullable    = true
}

variable "budget_name" {
  description = "Deployment-specific AWS monthly cost-budget name."
  type        = string
}

variable "monthly_budget_usd" {
  description = "Monthly AWS cost budget in USD."
  type        = number
  default     = 40

  validation {
    condition     = var.monthly_budget_usd > 0
    error_message = "monthly_budget_usd must be positive."
  }
}

variable "budget_notification_emails" {
  description = "Email addresses for budget notifications. Empty disables the budget resource."
  type        = set(string)
  default     = []
}

variable "tags" {
  description = "Additional non-sensitive resource tags."
  type        = map(string)
  default     = {}
}
