# =============================================================================
# Spike C4-B3 / C2 — PoC AWS SES Receiving -> S3 -> SNS -> SQS. BORRADOR, NO APLICADO.
# Requiere `terraform fmt/init -backend=false/validate` por el propietario y
# APROBACIÓN de inventario/presupuesto (../README.md §A) antes de `apply`.
#
# Remediación INFRA-H1..L3 (ver ../REMEDIATION_INFRA_H1_L3.md). Diseño sin Lambda:
# SES -> acción S3 (MIME crudo, SSE-KMS) + notificación SNS nativa (receipt.recipients
# + objectKey) -> SQS. El ledger durable (processed/quarantine/rejected) vive en S3.
# =============================================================================

data "aws_caller_identity" "current" {}

locals {
  account_id    = data.aws_caller_identity.current.account_id
  bucket_name   = "tribuu-${var.bucket_suffix}-inbound-raw-${local.account_id}"
  rule_set_name = "tribuu-poc-c4b3"
  rule_name     = "capture-to-s3"
  # ARN de la receipt-rule como STRING (no referencia a recurso) para romper ciclos de policy.
  receipt_rule_arn = "arn:aws:ses:us-east-1:${local.account_id}:receipt-rule-set/${local.rule_set_name}:receipt-rule/${local.rule_name}"
  # Principal que puede ASUMIR el rol worker (credenciales temporales STS). Por defecto root
  # de la cuenta (amplio) — se RECOMIENDA fijar un bootstrap principal explícito (variables.tf).
  worker_assumer = var.worker_assumer_principal_arn != "" ? var.worker_assumer_principal_arn : "arn:aws:iam::${local.account_id}:root"
}

# Prefijos: ambos deben terminar en '/' y NO solaparse (evita colisiones RAW/markers).
check "prefixes_disjuntos" {
  assert {
    condition = (
      endswith(var.raw_object_prefix, "/") && endswith(var.markers_prefix, "/") &&
      !startswith(var.raw_object_prefix, var.markers_prefix) &&
      !startswith(var.markers_prefix, var.raw_object_prefix)
    )
    error_message = "raw_object_prefix y markers_prefix deben terminar en '/' y no solaparse."
  }
}

# --- KMS CMK para SSE-KMS de S3 y SNS (NO la message-encryption client-side de SES) ---
resource "aws_kms_key" "evidence" {
  description             = "Tribuu PoC C4B3 - SSE-KMS inbound evidence"
  deletion_window_in_days = 7
  enable_key_rotation     = true

  # La key policy REEMPLAZA la default: root (evita lockout) + SES (S3 SSE-KMS y SNS).
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "EnableRootAndIAM"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::${local.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        # REQUERIDO (INFRA-H4): sin GenerateDataKey el PutObject SSE-KMS de SES falla (-> rebote).
        # Decrypt es necesario para la entrega a bucket SSE-KMS y para SNS cifrado.
        Sid       = "AllowSESUseOfKey"
        Effect    = "Allow"
        Principal = { Service = "ses.amazonaws.com" }
        Action    = ["kms:GenerateDataKey*", "kms:Decrypt"]
        Resource  = "*"
        Condition = {
          StringEquals = {
            "AWS:SourceAccount" = local.account_id
            "AWS:SourceArn"     = local.receipt_rule_arn
          }
        }
      }
    ]
  })
}

resource "aws_kms_alias" "evidence" {
  name          = "alias/tribuu-poc-c4b3-evidence"
  target_key_id = aws_kms_key.evidence.key_id
}

# --- S3 bucket: copia durable del MIME crudo + ledger durable (markers/) ---
resource "aws_s3_bucket" "raw" {
  bucket        = local.bucket_name
  force_destroy = true # PoC: permite destroy con objetos presentes
}

resource "aws_s3_bucket_public_access_block" "raw" {
  bucket                  = aws_s3_bucket.raw.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "raw" {
  bucket = aws_s3_bucket.raw.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.evidence.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_versioning" "raw" {
  bucket = aws_s3_bucket.raw.id
  versioning_configuration { status = "Enabled" }
}

# Retención >= 30 d: supera SQS (máx 14 d), DLQ y ventana de reconciliación/investigación (H7).
resource "aws_s3_bucket_lifecycle_configuration" "raw" {
  bucket = aws_s3_bucket.raw.id
  rule {
    id     = "poc-expire"
    status = "Enabled"
    filter {}
    expiration { days = var.object_expiration_days }
    noncurrent_version_expiration { noncurrent_days = var.object_expiration_days }
  }
}

# Bucket policy: TLS-only + PutObject SOLO a SES (SourceAccount + SourceArn=receipt-rule).
resource "aws_s3_bucket_policy" "raw" {
  bucket = aws_s3_bucket.raw.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = [aws_s3_bucket.raw.arn, "${aws_s3_bucket.raw.arn}/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      },
      {
        Sid       = "AllowSESPuts"
        Effect    = "Allow"
        Principal = { Service = "ses.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.raw.arn}/${var.raw_object_prefix}*"
        Condition = {
          StringEquals = {
            "AWS:SourceAccount" = local.account_id
            "AWS:SourceArn"     = local.receipt_rule_arn
          }
        }
      }
    ]
  })
}

# --- SNS: notificación nativa de SES (recipients + objectKey), cifrada en reposo (H4/M5) ---
resource "aws_sns_topic" "receipt" {
  name              = "tribuu-poc-c4b3-receipt"
  kms_master_key_id = aws_kms_key.evidence.id # SSE en reposo. SES publica bajo AllowSESUseOfKey. # VERIFY
}

resource "aws_sns_topic_policy" "receipt" {
  arn = aws_sns_topic.receipt.arn
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowSESPublish"
      Effect    = "Allow"
      Principal = { Service = "ses.amazonaws.com" }
      Action    = "SNS:Publish"
      Resource  = aws_sns_topic.receipt.arn
      Condition = {
        StringEquals = {
          "AWS:SourceAccount" = local.account_id
          "AWS:SourceArn"     = local.receipt_rule_arn
        }
      }
    }]
  })
}

# --- SQS: cola intake + DLQ del consumidor + DLQ de la suscripción SNS (H3) ---
# SSE gestionada por SQS (cifrado en reposo sin cross-grant de CMK) (M5/H4).
resource "aws_sqs_queue" "dlq" {
  name                      = "tribuu-poc-c4b3-consumer-dlq"
  message_retention_seconds = 1209600 # 14 d (máx)
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "sns_dlq" {
  name                      = "tribuu-poc-c4b3-sns-dlq"
  message_retention_seconds = 1209600
  sqs_managed_sse_enabled   = true
}

resource "aws_sqs_queue" "intake" {
  name                       = "tribuu-poc-c4b3-intake"
  message_retention_seconds  = 1209600
  visibility_timeout_seconds = 300 # VERIFY: alineado con el heartbeat del worker (ChangeMessageVisibility)
  sqs_managed_sse_enabled    = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 5
  })
}

# La cola intake acepta SOLO de este SNS; la SNS-DLQ acepta SOLO de este SNS.
resource "aws_sqs_queue_policy" "intake" {
  queue_url = aws_sqs_queue.intake.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowSNSSendMessage"
      Effect    = "Allow"
      Principal = { Service = "sns.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.intake.arn
      Condition = { ArnEquals = { "aws:SourceArn" = aws_sns_topic.receipt.arn } }
    }]
  })
}

resource "aws_sqs_queue_policy" "sns_dlq" {
  queue_url = aws_sqs_queue.sns_dlq.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowSNSSendMessage"
      Effect    = "Allow"
      Principal = { Service = "sns.amazonaws.com" }
      Action    = "sqs:SendMessage"
      Resource  = aws_sqs_queue.sns_dlq.arn
      Condition = { ArnEquals = { "aws:SourceArn" = aws_sns_topic.receipt.arn } }
    }]
  })
}

# Suscripción SNS->SQS con DLQ INDEPENDIENTE para fallos de entrega de la suscripción (H3).
resource "aws_sns_topic_subscription" "intake" {
  topic_arn            = aws_sns_topic.receipt.arn
  protocol             = "sqs"
  endpoint             = aws_sqs_queue.intake.arn
  raw_message_delivery = true
  redrive_policy       = jsonencode({ deadLetterTargetArn = aws_sqs_queue.sns_dlq.arn })
  depends_on           = [aws_sqs_queue_policy.intake, aws_sqs_queue_policy.sns_dlq]
}

# --- Alarmas efectivamente provisionadas (M4): profundidad de ambas DLQ ---
resource "aws_sns_topic" "alerts" {
  name = "tribuu-poc-c4b3-alerts"
}

resource "aws_sns_topic_subscription" "alerts_email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.budget_alarm_email
}

resource "aws_cloudwatch_metric_alarm" "consumer_dlq" {
  alarm_name          = "tribuu-poc-c4b3-consumer-dlq-nonempty"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.dlq.name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"
}

resource "aws_cloudwatch_metric_alarm" "sns_dlq" {
  alarm_name          = "tribuu-poc-c4b3-sns-dlq-nonempty"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.sns_dlq.name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  alarm_actions       = [aws_sns_topic.alerts.arn]
  treat_missing_data  = "notBreaching"
}

# --- SES Email Receiving ---
resource "aws_ses_domain_identity" "poc" {
  domain = var.subdomain
}

resource "aws_ses_receipt_rule_set" "poc" {
  rule_set_name = local.rule_set_name
}

# Protección (INFRA-L): activar el rule set REEMPLAZA el activo existente. Opt-in explícito.
# Activación FINAL: solo tras existir la regla (dependencia explícita).
resource "aws_ses_active_receipt_rule_set" "poc" {
  count         = var.activate_rule_set ? 1 : 0
  rule_set_name = aws_ses_receipt_rule_set.poc.rule_set_name
  depends_on    = [aws_ses_receipt_rule.capture]
}

resource "aws_ses_receipt_rule" "capture" {
  name          = local.rule_name
  rule_set_name = aws_ses_receipt_rule_set.poc.rule_set_name
  recipients    = [var.subdomain] # catch-all del subdominio (PoC)
  enabled       = true
  scan_enabled  = true
  tls_policy    = "Require"

  s3_action {
    bucket_name       = aws_s3_bucket.raw.id
    object_key_prefix = var.raw_object_prefix
    topic_arn         = aws_sns_topic.receipt.arn
    position          = 1
  }

  # Dependencias explícitas: cifrado (SSE+KMS), policy del bucket y policy del SNS deben existir
  # ANTES de crear la regla (SES escribe AMAZON_SES_SETUP_NOTIFICATION al crearla).
  depends_on = [
    aws_s3_bucket_policy.raw,
    aws_s3_bucket_server_side_encryption_configuration.raw,
    aws_kms_key.evidence,
    aws_sns_topic_policy.receipt
  ]
}

# --- Rol IAM worker ASUMIBLE (credenciales TEMPORALES vía STS) (NEW-P5/M7) ---
resource "aws_iam_role" "worker" {
  name = "tribuu-poc-c4b3-worker"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowAssumeByBootstrap"
      Effect    = "Allow"
      Principal = { AWS = local.worker_assumer }
      Action    = "sts:AssumeRole"
    }]
  })
  max_session_duration = 3600 # credenciales de corta vida
}

resource "aws_iam_role_policy" "worker" {
  name = "tribuu-poc-c4b3-worker"
  role = aws_iam_role.worker.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      # Lectura del RAW y escritura del ledger durable (markers/). NADA más en el bucket.
      { Sid = "ReadRaw", Effect = "Allow", Action = ["s3:GetObject"], Resource = "${aws_s3_bucket.raw.arn}/${var.raw_object_prefix}*" },
      { Sid = "RWMarkers", Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject"], Resource = "${aws_s3_bucket.raw.arn}/${var.markers_prefix}*" },
      { Sid = "ListScoped", Effect = "Allow", Action = ["s3:ListBucket"], Resource = aws_s3_bucket.raw.arn, Condition = { StringLike = { "s3:prefix" = ["${var.raw_object_prefix}*", "${var.markers_prefix}*"] } } },
      { Sid = "Sqs", Effect = "Allow", Action = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:ChangeMessageVisibility", "sqs:GetQueueAttributes"], Resource = aws_sqs_queue.intake.arn },
      # Decrypt para leer RAW; GenerateDataKey para ESCRIBIR markers cifrados SSE-KMS.
      { Sid = "Kms", Effect = "Allow", Action = ["kms:Decrypt", "kms:GenerateDataKey*"], Resource = aws_kms_key.evidence.arn },
      # Permisos NEGATIVOS (M/L): nunca borrar ni escribir sobre el RAW.
      { Sid = "DenyRawMutation", Effect = "Deny", Action = ["s3:DeleteObject", "s3:PutObject"], Resource = "${aws_s3_bucket.raw.arn}/${var.raw_object_prefix}*" }
    ]
  })
}
# NOTA (M7/P5): el worker usa CREDENCIALES TEMPORALES vía `aws sts assume-role` del rol de
# arriba (max 1 h). No se crean access keys estáticas. La revocación es natural (expiración de
# la sesión) + eliminación del rol en el teardown (§D). Si on-AWS, usar instance/task role.

# --- Control de costos: AWS Budgets (ALERTA, no límite; ver README §G). Precios verif. 2026-11 ---
resource "aws_budgets_budget" "poc" {
  name         = "tribuu-poc-c4b3"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = [50, 80, 100]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.budget_alarm_email]
    }
  }
}
