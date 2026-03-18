# Contributing

## Розробка

```bash
git clone https://github.com/0502srv/posipaka.git
cd posipaka
python -m venv .venv
source .venv/bin/activate
pip install -e ".[all,dev]"
```

## Тести

```bash
pytest tests/ -v              # Всі тести
pytest tests/test_security.py # Security тести
pytest tests/smoke/           # Smoke тести
pytest --cov=posipaka         # З coverage
```

## Linting

```bash
ruff check posipaka/          # Lint
ruff format posipaka/         # Format
mypy posipaka/                # Type check
bandit -r posipaka/           # Security scan
```

## Commit Convention

Conventional Commits:

```
feat: add new persona "data scientist"
fix: injection detection for Ukrainian patterns
docs: update security overview
refactor: simplify cost guard logic
test: add chaos tests for degradation
```

## Signed Commits (рекомендовано)

```bash
# GPG
git config --global commit.gpgsign true
git config --global user.signingkey YOUR_KEY_ID

# SSH (простіше)
git config --global gpg.format ssh
git config --global user.signingkey ~/.ssh/id_ed25519
git config --global commit.gpgsign true
```

## PR Process

1. Fork → branch → code → tests → PR
2. CI must pass (lint, tests, security)
3. Review required for security/ changes
4. Conventional commit message
