.PHONY: help build up down restart logs shell test verify clean clean-all

# Detect docker/podman availability
COMPOSE_CMD := $(shell command -v docker-compose 2>/dev/null || command -v podman-compose 2>/dev/null || echo "docker-compose")
COMPOSE_FILE := docker-compose.yml

# Color output
GREEN := \033[0;32m
YELLOW := \033[0;33m
BLUE := \033[0;34m
NC := \033[0m # No Color

help: ## Show all available targets
	@echo "$(BLUE)Bitbucket MCP Server - Available Targets$(NC)"
	@echo ""
	@echo "$(GREEN)Build & Container Management:$(NC)"
	@echo "  $(YELLOW)make build$(NC)         Build Docker image with docker-compose"
	@echo "  $(YELLOW)make up$(NC)            Start container in background"
	@echo "  $(YELLOW)make down$(NC)          Stop and remove container"
	@echo "  $(YELLOW)make restart$(NC)       Restart container"
	@echo ""
	@echo "$(GREEN)Monitoring & Access:$(NC)"
	@echo "  $(YELLOW)make logs$(NC)          Show container logs (tail -f)"
	@echo "  $(YELLOW)make shell$(NC)         Open interactive shell in container"
	@echo ""
	@echo "$(GREEN)Testing & Verification:$(NC)"
	@echo "  $(YELLOW)make test$(NC)          Run tests in container"
	@echo "  $(YELLOW)make verify$(NC)        Test Bitbucket authentication"
	@echo ""
	@echo "$(GREEN)Cleanup:$(NC)"
	@echo "  $(YELLOW)make clean$(NC)         Remove containers and images"
	@echo "  $(YELLOW)make clean-all$(NC)     Clean everything including volumes"
	@echo ""
	@echo "$(GREEN)Using:$(NC) $(COMPOSE_CMD)"
	@echo ""

build: ## Build Docker image with docker-compose
	@echo "$(BLUE)Building Docker image...$(NC)"
	$(COMPOSE_CMD) -f $(COMPOSE_FILE) build --no-cache
	@echo "$(GREEN)Build complete!$(NC)"

up: ## Start container in background
	@echo "$(BLUE)Starting container...$(NC)"
	$(COMPOSE_CMD) -f $(COMPOSE_FILE) up -d
	@echo "$(GREEN)Container started!$(NC)"
	@echo "Run '$(YELLOW)make logs$(NC)' to view logs"

down: ## Stop and remove container
	@echo "$(BLUE)Stopping container...$(NC)"
	$(COMPOSE_CMD) -f $(COMPOSE_FILE) down
	@echo "$(GREEN)Container stopped!$(NC)"

restart: ## Restart container
	@echo "$(BLUE)Restarting container...$(NC)"
	$(COMPOSE_CMD) -f $(COMPOSE_FILE) restart
	@echo "$(GREEN)Container restarted!$(NC)"

logs: ## Show container logs (tail -f)
	@echo "$(BLUE)Showing container logs (Ctrl+C to exit)...$(NC)"
	$(COMPOSE_CMD) -f $(COMPOSE_FILE) logs -f bitbucket-mcp

shell: ## Open interactive shell in container
	@echo "$(BLUE)Opening shell in container (type 'exit' to quit)...$(NC)"
	$(COMPOSE_CMD) -f $(COMPOSE_FILE) exec bitbucket-mcp /bin/bash

test: ## Run tests in container
	@echo "$(BLUE)Running tests...$(NC)"
	$(COMPOSE_CMD) -f $(COMPOSE_FILE) exec -T bitbucket-mcp uv run pytest -v tests/
	@echo "$(GREEN)Tests complete!$(NC)"

verify: ## Test Bitbucket authentication
	@echo "$(BLUE)Verifying Bitbucket authentication...$(NC)"
	@if [ -z "$(BITBUCKET_USERNAME)" ]; then \
		echo "$(YELLOW)Warning: BITBUCKET_USERNAME not set$(NC)"; \
	fi
	@if [ -z "$(BITBUCKET_PASSWORD)" ]; then \
		echo "$(YELLOW)Warning: BITBUCKET_PASSWORD not set$(NC)"; \
	fi
	@if [ -z "$(BITBUCKET_BASE_URL)" ]; then \
		echo "$(YELLOW)Warning: BITBUCKET_BASE_URL not set$(NC)"; \
	fi
	$(COMPOSE_CMD) -f $(COMPOSE_FILE) exec -T bitbucket-mcp \
		uv run python -c "from src.client import BitbucketClient; client = BitbucketClient(); print('$(GREEN)✓ Bitbucket authentication verified!$(NC)')"
	@echo "$(GREEN)Verification complete!$(NC)"

clean: ## Remove containers and images
	@echo "$(BLUE)Removing containers and images...$(NC)"
	$(COMPOSE_CMD) -f $(COMPOSE_FILE) down --rmi local
	@echo "$(GREEN)Cleanup complete!$(NC)"

clean-all: ## Clean everything including volumes
	@echo "$(BLUE)Removing all containers, images, and volumes...$(NC)"
	$(COMPOSE_CMD) -f $(COMPOSE_FILE) down --rmi all -v
	@echo "$(YELLOW)Removing Python cache and pytest artifacts...$(NC)"
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	@echo "$(GREEN)Full cleanup complete!$(NC)"

.DEFAULT_GOAL := help
