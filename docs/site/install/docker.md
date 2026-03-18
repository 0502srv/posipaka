# Docker

## Docker Compose (рекомендовано)

```bash
cd docker/
docker compose up -d
```

## Конфігурація

Створіть `.env` файл:

```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_OWNER_ID=your_telegram_id
```

## Volumes

```yaml
volumes:
  - posipaka_data:/home/agent/.posipaka
```

## Оновлення

```bash
docker compose pull
docker compose up -d
```

## Healthcheck

```bash
curl http://localhost:8080/api/v1/health
```
