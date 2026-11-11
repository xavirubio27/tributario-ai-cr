output "raw_bucket" {
  description = "Bucket S3 con el MIME crudo y el ledger durable (markers/)."
  value       = aws_s3_bucket.raw.id
}

output "raw_prefix" {
  value = var.raw_object_prefix
}

output "markers_prefix" {
  description = "Prefijo del ledger durable (processed/quarantine/rejected)."
  value       = var.markers_prefix
}

output "intake_queue_url" {
  description = "Cola SQS que consume el worker (SES->SNS->SQS)."
  value       = aws_sqs_queue.intake.url
}

output "consumer_dlq_url" {
  value = aws_sqs_queue.dlq.url
}

output "sns_subscription_dlq_url" {
  description = "DLQ independiente de la suscripción SNS->SQS (INFRA-H3)."
  value       = aws_sqs_queue.sns_dlq.url
}

output "sns_topic_arn" {
  value = aws_sns_topic.receipt.arn
}

output "alerts_topic_arn" {
  value = aws_sns_topic.alerts.arn
}

output "kms_key_arn" {
  value = aws_kms_key.evidence.arn
}

output "worker_role_arn" {
  description = "Rol asumible por el worker (credenciales temporales): aws sts assume-role --role-arn <este>."
  value       = aws_iam_role.worker.arn
}

output "alerts_email_confirmation_required" {
  description = "La suscripción de email al SNS 'alerts' nace PENDIENTE: el propietario debe CONFIRMARLA (clic en el correo de AWS) o las alarmas no se entregan."
  value       = "CONFIRMAR la suscripción de ${var.budget_alarm_email} al topic alerts antes de confiar en las alarmas."
}

output "rule_set_active" {
  description = "Si false, activar el rule set MANUALMENTE tras verificar que no hay otro activo (var.activate_rule_set)."
  value       = var.activate_rule_set
}

# Pasos MANUALES de DNS (subdominio desechable, externo a TF):
output "dns_mx_record_required" {
  description = "Añadir este MX en el DNS del subdominio de pruebas (NO productivo)."
  value       = "${var.subdomain}. MX 10 inbound-smtp.us-east-1.amazonaws.com"
}

output "ses_domain_verification_token" {
  description = "Crear TXT _amazonses.<subdominio> con este valor para verificar el dominio."
  value       = aws_ses_domain_identity.poc.verification_token
}
