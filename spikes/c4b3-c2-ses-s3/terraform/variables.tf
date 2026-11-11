variable "subdomain" {
  description = "Subdominio DESECHABLE de pruebas (NUNCA inbox.tribuu.ai). Ej: poc-inbox.ejemplo-test.xyz"
  type        = string
  validation {
    condition     = !can(regex("(?i)(^|\\.)tribuu\\.ai$", var.subdomain))
    error_message = "Prohibido usar un dominio productivo de Tribuu (tribuu.ai). Usa un subdominio desechable."
  }
}

variable "budget_alarm_email" {
  description = "Email del propietario para alarmas de presupuesto/CloudWatch (no PII de clientes)."
  type        = string
  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.budget_alarm_email))
    error_message = "budget_alarm_email debe ser un email válido."
  }
}

variable "monthly_budget_usd" {
  description = "Tope de presupuesto mensual (ALERTA, no límite de gasto). Ver README §G."
  type        = number
  default     = 10
  validation {
    condition     = var.monthly_budget_usd > 0 && var.monthly_budget_usd <= 50
    error_message = "Presupuesto de PoC acotado a 0 < valor <= 50 USD; valores mayores requieren aprobación explícita."
  }
}

variable "bucket_suffix" {
  description = "Sufijo para el nombre global del bucket S3 (DNS-safe)."
  type        = string
  default     = "poc-c4b3"
  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$", var.bucket_suffix))
    error_message = "bucket_suffix: minúsculas/dígitos/guiones, 3-40 chars, sin guion inicial/final (DNS-safe)."
  }
}

variable "raw_object_prefix" {
  description = "Prefijo de clave para los objetos MIME crudos."
  type        = string
  default     = "inbound-raw/"
}

variable "markers_prefix" {
  description = "Prefijo del ledger durable (processed/quarantine/rejected)."
  type        = string
  default     = "markers/"
}

variable "object_expiration_days" {
  description = "Expiración de objetos S3. Debe superar la ventana máxima de SQS/DLQ/reconciliación/investigación (SQS máx 14 d). PoC inicial: 30 d."
  type        = number
  default     = 30
  validation {
    condition     = var.object_expiration_days >= 30
    error_message = "La retención debe ser >= 30 d para superar SQS/DLQ/reconciliación (INFRA-H7)."
  }
}

variable "worker_assumer_principal_arn" {
  description = "ARN del principal bootstrap ESPECÍFICO que asume el rol worker vía STS (credenciales temporales). OBLIGATORIO; NO se admite root — debe ser user/ o role/."
  type        = string
  validation {
    condition     = can(regex("^arn:aws:iam::[0-9]{12}:(user|role)/.+$", var.worker_assumer_principal_arn))
    error_message = "Debe ser un ARN IAM específico (user/ o role/). NO se admite root ni vacío (NEW-P5)."
  }
}

variable "activate_rule_set" {
  description = "Si true, activa el receipt rule set. PELIGRO: reemplaza el rule set ACTIVO existente en la cuenta. Dejar en false y activar manualmente tras verificar que el sandbox no tiene otro activo (INFRA-L: protección de rule set existente)."
  type        = bool
  default     = false
}
