# Phase 43: Outputs

output "server_ip" {
  description = "Public IPv4 address of the Posipaka server"
  value       = hcloud_server.posipaka_prod.ipv4_address
}

output "server_status" {
  description = "Server status"
  value       = hcloud_server.posipaka_prod.status
}

output "server_id" {
  description = "Hetzner server ID"
  value       = hcloud_server.posipaka_prod.id
}

output "domain" {
  description = "Configured domain"
  value       = var.domain
}

output "volume_id" {
  description = "Data volume ID"
  value       = hcloud_volume.data.id
}
