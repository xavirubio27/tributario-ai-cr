# =============================================================================
# Spike C4-B3 / C2 — PoC AWS SES Receiving -> S3. BORRADOR IaC, NO APLICADO.
# Requiere `terraform fmt/init -backend=false/validate` por el propietario y
# APROBACIÓN de inventario/presupuesto (../README.md §A) antes de `apply`.
#
# Diseño: SES receipt rule -> acción S3 (MIME crudo) + notificación SNS nativa
# -> SQS (portador DURABLE y AUTORITATIVO de receipt.recipients + objectKey).
# SIN Lambda: los destinatarios del SOBRE vienen de SES, no de un sidecar ni
# de cabeceras MIME. Resuelve el hueco "Lambda falla antes del sidecar".
# =============================================================================

data "aws_caller_identity" "current" {}

locals {
  account_id    = data.aws_caller_identity.current.account_id
  bucket_name   = "tribuu-${var.bucket_suffix}-inbound-raw-${local.account_id}"
  rule_set_name = "tribuu-poc-c4b3"
  rule_name     = "capture-to-s3"
  # ARN de la receipt-rule (string, no referencia a recurso) para romper ciclos en las policies.
  receipt_rule_arn = "arn:aws:ses:us-east-1:${local.account_id}:receipt-rule-set/${local.rule_set_name}:receipt-rule/${local.rule_name}"
}

# --- KMS CMK para SSE-KMS del bucket (NO la message-encryption client-side de SES) ---
resource "aws_kms_key" "evidence" {
  description             = "Tribuu PoC C4B3 - SSE-KMS inbound evidence"
  deletion_window_in_days = 7
  enable_key_rotation     = true

  # La key policy REEMPLAZA la default: incluir root (evita lockout) + SES GenerateDataKey.
  # El worker obtiene kms:Decrypt vía su IAM policy (la sentencia root habilita IAM).
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
        # REQUERIDO: sin esto, el PutObject de SES a un bucket SSE-KMS FALLA (-> rebote).
        Sid       = "AllowSESGenerateDataKey"
        Effect    = "Allow"
        Principal = { Service = "ses.amazonaws.com" }
        Action    = ["kms:GenerateDataKey*"]
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

# --- S3 bucket: copia durable del MIME crudo ---
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

# --- SNS: notificación nativa de SES (recipients + objectKey), sin body ---
resource "aws_sns_topic" "receipt" {
  name = "tribuu-poc-c4b3-receipt"
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

# --- SQS: cola durable que consume el worker + DLQ ---
resource "aws_sqs_queue" "dlq" {
  name                      = "tribuu-poc-c4b3-dlq"
  message_retention_seconds = 1209600 # 14 d
}

resource "aws_sqs_queue" "intake" {
  name                       = "tribuu-poc-c4b3-intake"
  message_retention_seconds  = 1209600 # 14 d
  visibility_timeout_seconds = 300     # VERIFY: > peor tiempo de procesamiento del worker
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 5
  })
}

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

resource "aws_sns_topic_subscription" "intake" {
  topic_arn            = aws_sns_topic.receipt.arn
  protocol             = "sqs"
  endpoint             = aws_sqs_queue.intake.arn
  raw_message_delivery = true
}

# --- SES Email Receiving ---
resource "aws_ses_domain_identity" "poc" {
  domain = var.subdomain
}

resource "aws_ses_receipt_rule_set" "poc" {
  rule_set_name = local.rule_set_name
}

resource "aws_ses_active_receipt_rule_set" "poc" {
  rule_set_name = aws_ses_receipt_rule_set.poc.rule_set_name
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
    topic_arn         = aws_sns_topic.receipt.arn # notificación nativa con recipients + objectKey
    position          = 1
  }

  depends_on = [
    aws_s3_bucket_policy.raw,
    aws_kms_key.evidence,
    aws_sns_topic_policy.receipt
  ]
}

# --- Usuario IAM worker (PoC, scoped, de corta vida; eliminar en teardown) ---
resource "aws_iam_user" "worker" {
  name          = "tribuu-poc-c4b3-worker"
  force_destroy = true
}

resource "aws_iam_user_policy" "worker" {
  name = "tribuu-poc-c4b3-worker"
  user = aws_iam_user.worker.name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:GetObject"], Resource = "${aws_s3_bucket.raw.arn}/${var.raw_object_prefix}*" },
      { Effect = "Allow", Action = ["s3:ListBucket"], Resource = aws_s3_bucket.raw.arn, Condition = { StringLike = { "s3:prefix" = ["${var.raw_object_prefix}*"] } } },
      { Effect = "Allow", Action = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"], Resource = aws_sqs_queue.intake.arn },
      { Effect = "Allow", Action = ["kms:Decrypt"], Resource = aws_kms_key.evidence.arn }
    ]
  })
}
# NOTA: la access key del worker se crea FUERA de TF (o con aws_iam_access_key en un apply
# aparte) y se ELIMINA en el teardown. No se emite aquí para no persistir secretos en el state.

# --- Control de costos: AWS Budgets (ALERTA, no límite de gasto) + ver README §G ---
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
