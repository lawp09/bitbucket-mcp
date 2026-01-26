.PHONY: help build up down restart logs shell test verify clean

# Detect docker/podman
COMPOSE := $(shell command -v docker-compose 2>/dev/null || command -v podman-compose 2>/dev/null)

help:
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@echo "  build    Build Docker image"
	@echo "  up       Start container"
	@echo "  down     Stop container"
	@echo "  restart  Restart container"
	@echo "  logs     Show logs (tail -f)"
	@echo "  shell    Open shell in container"
	@echo "  test     Run tests"
	@echo "  verify   Test Bitbucket authentication"
	@echo "  clean    Remove containers and images"

build:
	$(COMPOSE) build --no-cache

up:
	$(COMPOSE) up -d

down:
	$(COMPOSE) down

restart:
	$(COMPOSE) restart

logs:
	$(COMPOSE) logs -f

shell:
	$(COMPOSE) exec bitbucket-mcp /bin/bash

test:
	pytest -v tests/

verify:
	$(COMPOSE) exec -T bitbucket-mcp python -c \
		"import os; from src.client import BitbucketClient; BitbucketClient(os.environ['BITBUCKET_USERNAME'], os.environ['BITBUCKET_TOKEN'], os.environ['BITBUCKET_WORKSPACE']); print('OK: Bitbucket client initialized')"

clean:
	$(COMPOSE) down --rmi local
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true

.DEFAULT_GOAL := help
