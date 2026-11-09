output "raw_bucket" {
  description = "Bucket S3 con el MIME crudo."
  value       = aws_s3_bucket.raw.id
}

output "intake_queue_url" {
  description = "Cola SQS que consume el worker (SES->SNS->SQS)."
  value       = aws_sqs_queue.intake.url
}

output "dlq_url" {
  value = aws_sqs_queue.dlq.url
}

output "sns_topic_arn" {
  value = aws_sns_topic.receipt.arn
}

output "kms_key_arn" {
  value = aws_kms_key.evidence.arn
}

output "worker_user_name" {
  description = "Crear access key de corta vida para este usuario (fuera de TF) y ELIMINARLA en teardown."
  value       = aws_iam_user.worker.name
}

# Pasos MANUALES de DNS para el propietario (subdominio desechable, externo a TF):
output "dns_mx_record_required" {
  description = "Añadir este MX en el DNS del subdominio de pruebas (NO productivo)."
  value       = "${var.subdomain}. MX 10 inbound-smtp.us-east-1.amazonaws.com"
}

output "ses_domain_verification_token" {
  description = "Crear TXT _amazonses.<subdominio> con este valor para verificar el dominio."
  value       = aws_ses_domain_identity.poc.verification_token
}
