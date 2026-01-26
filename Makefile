.PHONY: help build up down restart logs shell test verify clean

# Detect container runtime (prefer podman, fallback to docker)
RUNTIME := $(shell command -v podman 2>/dev/null || command -v docker 2>/dev/null)
IMAGE := bitbucket-mcp-py:latest
CONTAINER := bitbucket-mcp

help:
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@echo "  build    Build container image"
	@echo "  up       Start container"
	@echo "  down     Stop container"
	@echo "  restart  Restart container"
	@echo "  logs     Show logs (tail -f)"
	@echo "  shell    Open shell in container"
	@echo "  test     Run tests locally"
	@echo "  verify   Test Bitbucket authentication"
	@echo "  clean    Remove container and image"
	@echo ""
	@echo "Using: $(RUNTIME)"

build:
	$(RUNTIME) build --no-cache -t $(IMAGE) .

up:
	$(RUNTIME) run -d --name $(CONTAINER) --env-file .env $(IMAGE)

down:
	$(RUNTIME) stop $(CONTAINER) 2>/dev/null || true
	$(RUNTIME) rm $(CONTAINER) 2>/dev/null || true

restart: down up

logs:
	$(RUNTIME) logs -f $(CONTAINER)

shell:
	$(RUNTIME) exec -it $(CONTAINER) /bin/bash

test:
	pytest -v tests/

verify:
	$(RUNTIME) exec $(CONTAINER) python -c \
		"import os; from src.client import BitbucketClient; BitbucketClient(os.environ['BITBUCKET_USERNAME'], os.environ['BITBUCKET_TOKEN'], os.environ['BITBUCKET_WORKSPACE']); print('OK: Bitbucket client initialized')"

clean: down
	$(RUNTIME) rmi $(IMAGE) 2>/dev/null || true
	@find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	@find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true

.DEFAULT_GOAL := help
