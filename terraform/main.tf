# Main infrastructure — Hetzner VPS + Cloudflare DNS

# ── SSH Key ──────────────────────────────────────────────────────────────
resource "hcloud_ssh_key" "deploy" {
  name       = "posipaka-deploy"
  public_key = var.deploy_key
}

# ── Volume for persistent data ──────────────────────────────────────────
resource "hcloud_volume" "data" {
  name     = "posipaka-data"
  size     = 20 # GB
  location = var.location
  format   = "ext4"
}

# ── VPS Instance ─────────────────────────────────────────────────────────
resource "hcloud_server" "posipaka_prod" {
  name        = "posipaka-prod"
  server_type = var.server_type
  image       = var.image
  location    = var.location

  ssh_keys = [hcloud_ssh_key.deploy.id]

  user_data = templatefile("${path.module}/cloud-init.yaml", {
    deploy_key  = var.deploy_key
    env_file    = var.prod_env_b64
    volume_id   = hcloud_volume.data.id
    domain      = var.domain
  })

  labels = {
    environment = "production"
    project     = "posipaka"
    managed_by  = "terraform"
  }

  firewall_ids = [hcloud_firewall.posipaka.id]
}

# ── Volume attachment ────────────────────────────────────────────────────
resource "hcloud_volume_attachment" "data" {
  volume_id = hcloud_volume.data.id
  server_id = hcloud_server.posipaka_prod.id
  automount = true
}

# ── Firewall ─────────────────────────────────────────────────────────────
resource "hcloud_firewall" "posipaka" {
  name = "posipaka-firewall"

  # SSH — only from admin IP
  rule {
    direction  = "in"
    port       = "22"
    protocol   = "tcp"
    source_ips = [var.admin_ip]
  }

  # HTTPS
  rule {
    direction  = "in"
    port       = "443"
    protocol   = "tcp"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  # HTTP (redirect to HTTPS)
  rule {
    direction  = "in"
    port       = "80"
    protocol   = "tcp"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  # ICMP (ping)
  rule {
    direction  = "in"
    protocol   = "icmp"
    source_ips = ["0.0.0.0/0", "::/0"]
  }
}

# ── DNS via Cloudflare ───────────────────────────────────────────────────
resource "cloudflare_record" "posipaka_root" {
  zone_id = var.cloudflare_zone_id
  name    = "@"
  content = hcloud_server.posipaka_prod.ipv4_address
  type    = "A"
  proxied = true # Cloudflare CDN + DDoS protection
}

resource "cloudflare_record" "posipaka_docs" {
  zone_id = var.cloudflare_zone_id
  name    = "docs"
  content = "posipaka.github.io"
  type    = "CNAME"
  proxied = false
}
