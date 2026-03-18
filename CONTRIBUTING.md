# Contributing to Posipaka

Thank you for your interest in contributing!

## Development Setup

```bash
git clone https://github.com/0502srv/posipaka.git
cd posipaka
python -m venv .venv
source .venv/bin/activate
pip install -e ".[all,dev]"
pre-commit install
```

## Running Tests

```bash
pytest tests/ -v
ruff check posipaka/
mypy posipaka/
```

## Code Style

- Python 3.11+, asyncio-first
- Ruff for linting (config in pyproject.toml)
- Type hints on all public functions
- Docstrings for classes and public methods

## Security

- **CostGuard.check_before_call()** before EVERY LLM call
- **InjectionDetector.check()** on EVERY external message
- **sanitize_external_content()** for email/web/file content
- **requires_approval=True** on destructive tools
- **Audit log** for every action
- Never log secrets

## Pull Request Process

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Write tests for your changes
4. Ensure all tests pass (`pytest tests/ -v`)
5. Ensure linting passes (`ruff check posipaka/`)
6. Submit a Pull Request

## Translations

```bash
cp -r posipaka/utils/i18n/locale/en posipaka/utils/i18n/locale/YOUR_LANG
# Translate values (keep keys and {parameters} unchanged)
posipaka i18n validate --lang YOUR_LANG
```

## Commit Signing (Recommended)

```bash
git config --global gpg.format ssh
git config --global user.signingkey ~/.ssh/id_ed25519
git config --global commit.gpgsign true
```

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
