variable "subdomain" {
  description = "Subdominio DESECHABLE de pruebas (NUNCA inbox.tribuu.ai). Ej: poc-inbox.ejemplo-test.xyz"
  type        = string
}

variable "monthly_budget_usd" {
  description = "Tope de presupuesto mensual (guardrail). Supera => revisar/parar."
  type        = number
  default     = 10
}

variable "budget_alarm_email" {
  description = "Email del propietario para alarmas de presupuesto (no PII de clientes)."
  type        = string
}

variable "bucket_suffix" {
  description = "Sufijo único para el nombre global del bucket S3."
  type        = string
  default     = "poc-c4b3"
}

variable "raw_object_prefix" {
  description = "Prefijo de clave para los objetos MIME crudos."
  type        = string
  default     = "inbound-raw/"
}

variable "object_expiration_days" {
  description = "Expiración de objetos S3 en la PoC (lifecycle). Datos sintéticos, retención corta."
  type        = number
  default     = 7
}
