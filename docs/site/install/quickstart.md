# Швидкий старт

## Вимоги

- Python 3.11+
- 2GB RAM (мінімум)
- API ключ для LLM (Anthropic, OpenAI, або Ollama для локального)

## Встановлення

### Один рядок (рекомендовано)

```bash
curl -fsSL https://posipaka.dev/install.sh | bash
```

### Через pip

```bash
pip install posipaka
posipaka setup
```

### З Docker

```bash
docker pull ghcr.io/user/posipaka:latest
docker run -v ~/.posipaka:/home/agent/.posipaka posipaka
```

## Налаштування

Wizard проведе вас через:

1. Вибір LLM провайдера (Anthropic / OpenAI / Ollama)
2. Введення API ключа
3. Налаштування месенджера (Telegram рекомендовано)
4. Вибір інтеграцій
5. Персоналізація агента

## Перший запуск

```bash
posipaka start
```

Або для CLI режиму:

```bash
posipaka chat
```

## Перевірка

```bash
posipaka doctor    # Діагностика
posipaka status    # Статус агента
```
