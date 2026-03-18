# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-03-17

### Added
- Core agent runtime with agentic loop (max 10 tool iterations)
- 6 messenger channels: Telegram, Discord, Slack, WhatsApp, Signal, CLI
- 16 integrations: shell, browser, gmail, calendar, github, notion, weather, news, crypto, wikipedia, smart_home, smart_email, social_media, documents, google_workspace, slack
- 4-layer memory system: RAM, SQLite, MEMORY.md, ChromaDB
- Hybrid search: Tantivy BM25 + ChromaDB embeddings with RRF fusion
- 7 builtin skills: summarize, translate, remind, research, finance, health
- Multi-agent orchestration with 5 specialized agents
- 34 builtin personas across 9 categories
- YAML workflow engine with conditions and variable passing
- Heartbeat engine + CronEngine for proactive behavior
- Voice message support (STT via Whisper, TTS via edge-tts)
- Document processing (PDF, DOCX, XLSX, images)
- Conversation threading for Telegram reply context
- Webhook health monitoring with auto-recovery

### Security
- Hash-chained audit logging (SHA-256)
- Injection detection (EN/UA/RU patterns)
- Shell sandbox with command validation
- SSRF protection with DNS rebinding defense
- Path traversal protection
- Skill sandboxing (AST validation + import whitelist)
- CSP nonces for inline scripts
- Concurrent session limits
- Secrets rotation policy
- GDPR data export/delete endpoints
- Webhook rate limiting (120 req/min per IP)

### Infrastructure
- FastAPI Web UI with auth, dashboard, and REST API
- Docker support (Dockerfile + docker-compose)
- Terraform IaC for Hetzner + Cloudflare
- CI/CD pipelines (GitHub Actions)
- SBOM generation (CycloneDX)
- Container image scanning (Trivy)
- MkDocs Material documentation
- i18n support (uk, en)
- Resource monitoring with auto-optimization
- Android/Termux platform support
- Blue-green deployment with auto-rollback
