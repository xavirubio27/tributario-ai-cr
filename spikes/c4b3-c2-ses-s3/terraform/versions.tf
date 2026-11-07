# Spike C4-B3 / C2 — PoC SES→S3. IaC NO APLICADA (ver ../README.md §A/§B).
terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "aws" {
  region = "us-east-1" # SES Email Receiving autorizado solo en regiones soportadas; us-east-1 (PoC)
  default_tags {
    tags = {
      Project = "tribuu"
      Spike   = "c4b3-c2-ses-s3"
      Env     = "poc-sandbox"
      Owner   = "tribuu-poc"
    }
  }
}
