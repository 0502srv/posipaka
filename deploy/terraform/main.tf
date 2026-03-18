# Phase 43: Infrastructure as Code — Hetzner Cloud + Cloudflare
# Використання:
#   cd deploy/terraform
#   terraform init
#   terraform plan
#   terraform apply

terraform {
  required_version = ">= 1.5"
  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.45"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.0"
    }
  }
}

# --- Variables ---

variable "hcloud_token" {
  description = "Hetzner Cloud API token"
  type        = string
  sensitive   = true
}

variable "cloudflare_api_token" {
  description = "Cloudflare API token"
  type        = string
  sensitive   = true
  default     = ""
}

variable "cloudflare_zone_id" {
  description = "Cloudflare DNS zone ID"
  type        = string
  default     = ""
}

variable "domain" {
  description = "Domain name for Posipaka"
  type        = string
  default     = "posipaka.example.com"
}

variable "ssh_key_name" {
  description = "Name of SSH key in Hetzner"
  type        = string
  default     = "posipaka-deploy"
}

variable "server_type" {
  description = "Hetzner server type"
  type        = string
  default     = "cx22"  # 2 vCPU, 4GB RAM, 40GB — достатньо для agent
}

variable "location" {
  description = "Hetzner datacenter location"
  type        = string
  default     = "fsn1"  # Falkenstein, Germany
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "production"
}

# --- Providers ---

provider "hcloud" {
  token = var.hcloud_token
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

# --- SSH Key ---

data "hcloud_ssh_key" "deploy" {
  name = var.ssh_key_name
}

# --- Firewall ---

resource "hcloud_firewall" "posipaka" {
  name = "posipaka-${var.environment}"

  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "22"
    source_ips = ["0.0.0.0/0", "::/0"]
    description = "SSH"
  }

  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "80"
    source_ips = ["0.0.0.0/0", "::/0"]
    description = "HTTP"
  }

  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "443"
    source_ips = ["0.0.0.0/0", "::/0"]
    description = "HTTPS"
  }

  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "8080"
    source_ips = ["0.0.0.0/0", "::/0"]
    description = "Posipaka Web UI"
  }
}

# --- Server ---

resource "hcloud_server" "posipaka" {
  name        = "posipaka-${var.environment}"
  server_type = var.server_type
  location    = var.location
  image       = "ubuntu-24.04"
  ssh_keys    = [data.hcloud_ssh_key.deploy.id]

  firewall_ids = [hcloud_firewall.posipaka.id]

  user_data = file("${path.module}/cloud-init.yaml")

  labels = {
    app         = "posipaka"
    environment = var.environment
    managed_by  = "terraform"
  }
}

# --- DNS (Cloudflare, optional) ---

resource "cloudflare_record" "posipaka" {
  count   = var.cloudflare_zone_id != "" ? 1 : 0
  zone_id = var.cloudflare_zone_id
  name    = var.domain
  content = hcloud_server.posipaka.ipv4_address
  type    = "A"
  proxied = true
  ttl     = 1
}

# --- Outputs ---

output "server_ip" {
  value       = hcloud_server.posipaka.ipv4_address
  description = "Server IPv4 address"
}

output "server_ipv6" {
  value       = hcloud_server.posipaka.ipv6_address
  description = "Server IPv6 address"
}

output "ssh_command" {
  value       = "ssh root@${hcloud_server.posipaka.ipv4_address}"
  description = "SSH connection command"
}

output "web_ui_url" {
  value       = "http://${hcloud_server.posipaka.ipv4_address}:8080"
  description = "Web UI URL"
}
