output "lightsail_instance_name" {
  description = "Lightsail application instance name."
  value       = aws_lightsail_instance.app.name
}

output "public_ipv4_address" {
  description = "Attached static IPv4 address, or null for IPv6-only deployments."
  value       = try(aws_lightsail_static_ip.app[0].ip_address, null)
}

output "public_ipv6_addresses" {
  description = "Lightsail IPv6 addresses. Review them before creating external AAAA records."
  value       = aws_lightsail_instance.app.ipv6_addresses
}

output "backup_bucket_name" {
  description = "Private S3 bucket used by restic."
  value       = aws_s3_bucket.backup.id
}

output "backup_user_name" {
  description = "Least-privilege backup IAM user. Create and transfer its access key outside Terraform."
  value       = aws_iam_user.backup.name
}

output "restic_repository" {
  description = "Non-secret RESTIC_REPOSITORY value."
  value       = "s3:https://s3.${var.aws_region}.amazonaws.com/${aws_s3_bucket.backup.id}"
}
