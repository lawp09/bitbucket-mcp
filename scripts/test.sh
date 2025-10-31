#!/bin/bash
# Run tests

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo "Running tests..."
python -m pytest tests/ -v --cov=src --cov-report=term-missing

echo ""
echo "Tests complete!"
