# Monitoring stack — Prometheus + Grafana + AlertManager

# Monitoring is deployed as part of docker-compose on the same VPS.
# This file provides the configuration templates.

resource "local_file" "prometheus_config" {
  filename = "${path.module}/generated/prometheus.yml"
  content  = <<-YAML
    global:
      scrape_interval: 30s
      evaluation_interval: 30s

    rule_files:
      - /etc/prometheus/alerts.yml

    scrape_configs:
      - job_name: posipaka
        static_configs:
          - targets: ["posipaka-app:8080"]
        metrics_path: /api/v1/metrics
        scrape_interval: 15s

      - job_name: node
        static_configs:
          - targets: ["node-exporter:9100"]

      - job_name: cadvisor
        static_configs:
          - targets: ["cadvisor:8080"]
  YAML
}

resource "local_file" "alert_rules" {
  filename = "${path.module}/generated/alerts.yml"
  content  = <<-YAML
    groups:
      - name: posipaka
        rules:
          - alert: HighDiskUsage
            expr: (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"}) < 0.2
            for: 5m
            labels:
              severity: warning
            annotations:
              summary: "Disk usage > 80%"

          - alert: HighMemoryUsage
            expr: (1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) > 0.9
            for: 5m
            labels:
              severity: critical
            annotations:
              summary: "Memory usage > 90%"

          - alert: LLMErrorRate
            expr: rate(posipaka_llm_errors_total[5m]) > 0.08
            for: 2m
            labels:
              severity: warning
            annotations:
              summary: "LLM error rate > 5/min"

          - alert: HighCostBurn
            expr: posipaka_daily_cost_usd > 8
            labels:
              severity: warning
            annotations:
              summary: "Daily LLM cost exceeds $8"

          - alert: ServiceDown
            expr: up{job="posipaka"} == 0
            for: 1m
            labels:
              severity: critical
            annotations:
              summary: "Posipaka service is down"
  YAML
}

resource "local_file" "grafana_dashboard" {
  filename = "${path.module}/generated/grafana-posipaka.json"
  content  = <<-JSON
    {
      "dashboard": {
        "title": "Posipaka Overview",
        "uid": "posipaka-main",
        "panels": [
          {
            "title": "LLM Requests/min",
            "type": "timeseries",
            "targets": [{"expr": "rate(posipaka_llm_requests_total[5m]) * 60"}],
            "gridPos": {"h": 8, "w": 12, "x": 0, "y": 0}
          },
          {
            "title": "Daily Cost (USD)",
            "type": "stat",
            "targets": [{"expr": "posipaka_daily_cost_usd"}],
            "gridPos": {"h": 4, "w": 6, "x": 12, "y": 0}
          },
          {
            "title": "Active Sessions",
            "type": "stat",
            "targets": [{"expr": "posipaka_active_sessions"}],
            "gridPos": {"h": 4, "w": 6, "x": 18, "y": 0}
          },
          {
            "title": "Memory Usage",
            "type": "gauge",
            "targets": [{"expr": "1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)"}],
            "gridPos": {"h": 8, "w": 6, "x": 12, "y": 4}
          },
          {
            "title": "Error Rate",
            "type": "timeseries",
            "targets": [{"expr": "rate(posipaka_llm_errors_total[5m]) * 60"}],
            "gridPos": {"h": 8, "w": 12, "x": 0, "y": 8}
          },
          {
            "title": "Disk Usage",
            "type": "gauge",
            "targets": [{"expr": "1 - (node_filesystem_avail_bytes{mountpoint=\"/\"} / node_filesystem_size_bytes{mountpoint=\"/\"})"}],
            "gridPos": {"h": 8, "w": 6, "x": 18, "y": 4}
          }
        ],
        "time": {"from": "now-24h", "to": "now"},
        "refresh": "30s"
      }
    }
  JSON
}
