# Plan — Posipaka Production Readiness

## Критичні (блокують продакшн)

- [ ] **1. Виправити shell injection в deploy.sh** — замінити sed на Python скрипт для .env модифікації
- [ ] **2. Додати StartLimitBurst в systemd** — запобігти restart loop (`StartLimitBurst=5 StartLimitIntervalSec=300`)
- [ ] **3. Зробити CI строгим** — прибрати `continue-on-error: true` з mypy, bandit, pip-audit

## Важливі (покращують якість)

- [ ] **4. Встановити chromadb на сервер** — увімкнути semantic search
- [ ] **5. Виправити user_id передачу** — передавати реальний Telegram chat_id в tool context
- [ ] **6. Розглянути кращу модель** — `mistral-small` часто ігнорує інструкції, web search не викликає добровільно
- [ ] **7. Discord/Slack довести** — slash commands, approval buttons

## Бажані (nice to have)

- [ ] **8. Увімкнути MCP Tools**
- [ ] **9. Database migration step в blue-green deploy**
- [ ] **10. Integration tests в CI**

## Поточний стан деплою

- **Сервер:** 46.224.42.51 (Hetzner, Ubuntu 24.04)
- **Метод:** Native Python + systemd (не Docker)
- **Код:** /opt/posipaka (git pull origin main)
- **Дані:** ~/.posipaka
- **Web UI:** http://46.224.42.51:8080
- **Логи:** `journalctl -u posipaka -f`
- **Оновлення:** ручне `cd /opt/posipaka && git pull origin main && systemctl restart posipaka`

## Що працює на проді

- Telegram бот (polling, команди, voice, documents)
- Нагадування через CronEngine + APScheduler (створення + доставка)
- Web UI з авторизацією
- 57 зареєстрованих tools
- 35 персон
- Mistral Small LLM
- Обрізання довгих відповідей
- Жорсткий промпт з 10 правилами
