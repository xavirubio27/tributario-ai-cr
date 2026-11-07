output "raw_bucket" {
  description = "Bucket S3 con el MIME crudo."
  value       = aws_s3_bucket.raw.id
}

output "intake_queue_url" {
  description = "Cola SQS de intake durable."
  value       = aws_sqs_queue.intake.url
}

output "dlq_url" {
  value = aws_sqs_queue.dlq.url
}

output "kms_key_arn" {
  value = aws_kms_key.evidence.arn
}

# Pasos MANUALES de DNS para el propietario (el subdominio es desechable y externo a TF):
output "dns_mx_record_required" {
  description = "Añadir este MX en el DNS del subdominio de pruebas (NO productivo)."
  value       = "${var.subdomain}. MX 10 inbound-smtp.us-east-1.amazonaws.com"
}

output "ses_domain_verification_token" {
  description = "Crear un TXT _amazonses.<subdominio> con este valor para verificar el dominio."
  value       = aws_ses_domain_identity.poc.verification_token
}
