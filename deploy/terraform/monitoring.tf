# Phase 43: Monitoring stack (Prometheus + Grafana + Loki)
# Опціональний — додається через docker-compose на тому ж сервері

# Prometheus для метрик
resource "hcloud_server" "monitoring" {
  count       = var.environment == "production" ? 1 : 0
  name        = "posipaka-monitoring"
  server_type = "cx22"
  location    = var.location
  image       = "ubuntu-24.04"
  ssh_keys    = [data.hcloud_ssh_key.deploy.id]

  firewall_ids = [hcloud_firewall.posipaka.id]

  labels = {
    app         = "posipaka-monitoring"
    environment = var.environment
    managed_by  = "terraform"
  }

  user_data = <<-EOF
    #cloud-config
    package_update: true
    packages:
      - docker.io
      - docker-compose-v2

    runcmd:
      - systemctl enable docker
      - systemctl start docker
      - mkdir -p /opt/monitoring
      - |
        cat > /opt/monitoring/docker-compose.yml << 'COMPOSE'
        version: "3.8"
        services:
          prometheus:
            image: prom/prometheus:latest
            ports:
              - "9090:9090"
            volumes:
              - ./prometheus.yml:/etc/prometheus/prometheus.yml
              - prometheus_data:/prometheus
            restart: unless-stopped

          grafana:
            image: grafana/grafana:latest
            ports:
              - "3000:3000"
            environment:
              - GF_SECURITY_ADMIN_PASSWORD=changeme
              - GF_USERS_ALLOW_SIGN_UP=false
            volumes:
              - grafana_data:/var/lib/grafana
            restart: unless-stopped

          loki:
            image: grafana/loki:latest
            ports:
              - "3100:3100"
            volumes:
              - loki_data:/loki
            restart: unless-stopped

        volumes:
          prometheus_data:
          grafana_data:
          loki_data:
        COMPOSE
      - |
        cat > /opt/monitoring/prometheus.yml << 'PROM'
        global:
          scrape_interval: 30s

        scrape_configs:
          - job_name: posipaka
            metrics_path: /api/v1/health
            static_configs:
              - targets:
                  - ${hcloud_server.posipaka.ipv4_address}:8080
        PROM
      - cd /opt/monitoring && docker compose up -d
  EOF
}

output "monitoring_ip" {
  value       = var.environment == "production" ? hcloud_server.monitoring[0].ipv4_address : "N/A"
  description = "Monitoring server IP"
}

output "grafana_url" {
  value       = var.environment == "production" ? "http://${hcloud_server.monitoring[0].ipv4_address}:3000" : "N/A"
  description = "Grafana dashboard URL"
}
