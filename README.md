# Posipaka

**Персональний AI-агент для месенджерів.** Живе на вашому сервері, спілкується через Telegram, Discord, Slack, WhatsApp та Signal.

[![CI](https://github.com/0502srv/posipaka/actions/workflows/ci.yml/badge.svg)](https://github.com/0502srv/posipaka/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)

## Features

- **6 месенджерів** — Telegram, Discord, Slack, WhatsApp, Signal, CLI
- **16 інтеграцій** — Gmail, Calendar, GitHub, Browser, Shell, Wikipedia, Weather...
- **4-layer memory** — RAM, SQLite, MEMORY.md, ChromaDB (semantic search)
- **Multi-agent** — 5 спеціалізованих агентів (research, code, calendar, devops, analysis)
- **35 personas** — від Programming Tutor до Travel Planner
- **Voice & Vision** — голосові повідомлення (STT/TTS), аналіз зображень
- **Security-first** — injection detection (EN/UA/RU), audit logging, approval gates, SSRF protection
- **Self-hosted** — ваші дані залишаються на вашому сервері

## One-Command Deploy (VPS)

```bash
# SSH to your server, then:
git clone https://github.com/0502srv/posipaka.git /opt/posipaka
cd /opt/posipaka
bash scripts/deploy.sh
```

The script auto-detects Docker or native Python, sets up everything, creates a systemd service, and runs health checks.

## Quick Start (Local)

```bash
pip install posipaka[telegram]
posipaka setup    # interactive wizard
posipaka start
```

## Docker

```bash
git clone https://github.com/0502srv/posipaka.git
cd posipaka
cp .env.example .env
nano .env  # set LLM_API_KEY and TELEGRAM_TOKEN
docker compose -f docker/docker-compose.yml up -d
```

## Configuration

All settings via `.env` file or environment variables:

| Variable | Required | Description |
|----------|----------|-------------|
| `LLM_API_KEY` | Yes | Anthropic or OpenAI API key |
| `LLM_PROVIDER` | No | `anthropic` (default), `openai`, `ollama` |
| `TELEGRAM_TOKEN` | Yes* | Telegram bot token from @BotFather |
| `TELEGRAM_OWNER_ID` | No | Auto-set on first message |

See [`.env.example`](.env.example) for all options.

## Commands

```bash
posipaka start          # Start the agent
posipaka setup          # Interactive setup wizard
posipaka chat           # CLI REPL mode
posipaka status         # System status
posipaka config show    # Show configuration (secrets hidden)
```

## Architecture

```
Message → Gateway → InjectionDetector → Agent → LLM → Tools → Response
                                          ↕           ↕
                                       Memory     Approval Gates
                                    (4 layers)    (16 tools)
```

## Security

- **Injection detection** — multi-layer pattern matching (EN/UA/RU) + structural analysis
- **Approval gates** — destructive actions require user confirmation
- **Hash-chained audit log** — tamper-proof SHA-256 chain
- **Shell sandbox** — blocks `rm -rf /`, fork bombs, `curl|bash`
- **SSRF protection** — blocks internal IPs, DNS rebinding
- **Cost guard** — daily budget limits per LLM call

## Documentation

- [Contributing](CONTRIBUTING.md)

## Tech Stack

Python 3.11+ | FastAPI | SQLite | ChromaDB | Anthropic/OpenAI/Ollama

## License

[MIT](LICENSE)
