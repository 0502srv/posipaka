# Input variables

variable "hcloud_token" {
  description = "Hetzner Cloud API token"
  type        = string
  sensitive   = true
}

variable "cloudflare_api_token" {
  description = "Cloudflare API token"
  type        = string
  sensitive   = true
}

variable "cloudflare_zone_id" {
  description = "Cloudflare zone ID for the domain"
  type        = string
}

variable "domain" {
  description = "Domain name (e.g., posipaka.example.com)"
  type        = string
}

variable "admin_ip" {
  description = "Admin IP for SSH access (CIDR, e.g., 1.2.3.4/32)"
  type        = string
}

variable "deploy_key" {
  description = "SSH public key for deploy user"
  type        = string
}

variable "prod_env_b64" {
  description = "Base64-encoded .env file for production"
  type        = string
  sensitive   = true
}

variable "server_type" {
  description = "Hetzner server type"
  type        = string
  default     = "cx21" # 2 vCPU, 4GB RAM
}

variable "location" {
  description = "Hetzner datacenter location"
  type        = string
  default     = "hel1" # Helsinki (GDPR-friendly EU)
}

variable "image" {
  description = "OS image"
  type        = string
  default     = "ubuntu-22.04"
}
