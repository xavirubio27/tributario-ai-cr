# =============================================================================
# Spike C4-B3 / C2 — PoC AWS SES Receiving -> S3. BORRADOR IaC, NO APLICADO.
# Requiere `terraform validate`/`plan` y APROBACIÓN de inventario/presupuesto
# (../README.md §A) antes de `apply`. Marcadores `# VERIFY` = confirmar al planear.
# =============================================================================

data "aws_caller_identity" "current" {}

locals {
  account_id  = data.aws_caller_identity.current.account_id
  bucket_name = "tribuu-${var.bucket_suffix}-inbound-raw-${local.account_id}"
}

# --- KMS CMK para SSE-KMS del bucket (NO se usa la message-encryption client-side de SES) ---
resource "aws_kms_key" "evidence" {
  description             = "Tribuu PoC C4B3 - SSE-KMS inbound evidence"
  deletion_window_in_days = 7
  enable_key_rotation     = true
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
    expiration { days = var.object_expiration_days }
    noncurrent_version_expiration { noncurrent_days = var.object_expiration_days }
  }
}

# Bucket policy: TLS-only + permiso de escritura SOLO a SES (con condiciones de cuenta/ARN).
# Debe existir ANTES de crear la receipt rule (SES escribe AMAZON_SES_SETUP_NOTIFICATION al crearla).
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
          StringEquals = { "aws:Referer" = local.account_id } # VERIFY: AWS recomienda aws:SourceAccount/SourceArn
        }
      }
    ]
  })
}

# --- SQS: notificación durable + DLQ ---
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

# --- Lambda enqueue: lee receipt.recipients (SOBRE), escribe sidecar, encola ---
data "archive_file" "enqueue" {
  type        = "zip"
  source_file = "${path.module}/lambda/enqueue.py"
  output_path = "${path.module}/.build/enqueue.zip"
}

resource "aws_iam_role" "lambda" {
  name = "tribuu-poc-c4b3-lambda"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "lambda.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy" "lambda" {
  name = "tribuu-poc-c4b3-lambda"
  role = aws_iam_role.lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"], Resource = "arn:aws:logs:*:*:*" },
      { Effect = "Allow", Action = ["s3:PutObject"], Resource = "${aws_s3_bucket.raw.arn}/${var.raw_object_prefix}*" },
      { Effect = "Allow", Action = ["sqs:SendMessage"], Resource = aws_sqs_queue.intake.arn },
      { Effect = "Allow", Action = ["kms:GenerateDataKey", "kms:Encrypt"], Resource = aws_kms_key.evidence.arn }
    ]
  })
}

resource "aws_lambda_function" "enqueue" {
  function_name    = "tribuu-poc-c4b3-enqueue"
  role             = aws_iam_role.lambda.arn
  runtime          = "python3.12"
  handler          = "enqueue.handler"
  filename         = data.archive_file.enqueue.output_path
  source_code_hash = data.archive_file.enqueue.output_base64sha256
  timeout          = 30
  memory_size      = 256
  environment {
    variables = {
      INTAKE_QUEUE_URL = aws_sqs_queue.intake.url
      RAW_BUCKET       = aws_s3_bucket.raw.id
      RAW_PREFIX       = var.raw_object_prefix
    }
  }
}

resource "aws_lambda_permission" "ses_invoke" {
  statement_id  = "AllowSESInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.enqueue.function_name
  principal     = "ses.amazonaws.com"
  source_account = local.account_id
}

# --- SES Email Receiving ---
resource "aws_ses_domain_identity" "poc" {
  domain = var.subdomain
}

resource "aws_ses_receipt_rule_set" "poc" {
  rule_set_name = "tribuu-poc-c4b3"
}

resource "aws_ses_active_receipt_rule_set" "poc" {
  rule_set_name = aws_ses_receipt_rule_set.poc.rule_set_name
}

resource "aws_ses_receipt_rule" "capture" {
  name          = "capture-to-s3-and-enqueue"
  rule_set_name = aws_ses_receipt_rule_set.poc.rule_set_name
  recipients    = [var.subdomain] # captura todo el subdominio (catch-all PoC)
  enabled       = true
  scan_enabled  = true
  tls_policy    = "Require"

  s3_action {
    bucket_name       = aws_s3_bucket.raw.id
    object_key_prefix = var.raw_object_prefix
    position          = 1
  }
  lambda_action {
    function_arn    = aws_lambda_function.enqueue.arn
    invocation_type = "Event"
    position        = 2
  }

  depends_on = [aws_s3_bucket_policy.raw, aws_lambda_permission.ses_invoke]
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
# NOTA: la access key se crea fuera de TF (o con aws_iam_access_key) y se ELIMINA en teardown.
# No se emite aquí para no persistir secretos en el state. # VERIFY

# --- Control de costos: AWS Budgets + alarma ---
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
