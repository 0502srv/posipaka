.PHONY: install dev test lint type-check check start setup clean docker

install:
	pip install -e ".[all]"

dev:
	pip install -e ".[all,dev]"
	pre-commit install

test:
	pytest tests/ -v

lint:
	ruff check posipaka/

type-check:
	mypy posipaka/

check: lint type-check test

start:
	python -m posipaka start

setup:
	python -m posipaka setup

chat:
	python -m posipaka chat

docker:
	docker compose -f docker/docker-compose.yml up -d

docker-dev:
	docker compose -f docker/docker-compose.dev.yml up -d

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	rm -rf .mypy_cache .ruff_cache .pytest_cache htmlcov dist build *.egg-info
