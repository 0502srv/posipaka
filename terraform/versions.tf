# Phase 43: Terraform providers & backend
# Posipaka Infrastructure as Code
# GDPR-friendly EU datacenter (Helsinki)

terraform {
  required_version = ">= 1.5.0"

  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.45"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.20"
    }
  }

  backend "s3" {
    bucket = "posipaka-terraform-state"
    key    = "production/terraform.tfstate"
    region = "eu-central-1"
  }
}

provider "hcloud" {
  token = var.hcloud_token
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}
