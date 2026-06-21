.PHONY: test test-cov lint format run doctor backup clean help

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

test: ## Run tests
	pytest tests/ -v --tb=short

test-cov: ## Run tests with coverage
	pytest tests/ -v --tb=short --cov=src --cov-report=term-missing --cov-report=html

test-unit: ## Run unit tests only
	pytest tests/ -v --tb=short -m "not integration and not network"

test-integration: ## Run integration tests
	pytest tests/ -v --tb=short -m "integration"

lint: ## Run linting
	ruff check src/ hn2md/ tests/
	ruff format --check src/ hn2md/ tests/

format: ## Format code
	ruff format src/ hn2md/ tests/
	ruff check --fix src/ hn2md/ tests/

typecheck: ## Run type checking
	mypy src/ hn2md/ --ignore-missing-imports

run: ## Run the full pipeline
	hn2md release

doctor: ## Run health check
	hn2md doctor

backup: ## Backup the database
	hn2md backup

status: ## Show current job status
	hn2md status

audit: ## Audit content quality
	hn2md audit

clean: ## Clean generated files
	rm -rf output/jobs/*.json
	rm -rf .pytest_cache/
	rm -rf htmlcov/
	rm -rf .coverage
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

install: ## Install in development mode
	pip install -e ".[dev]"

install-hooks: ## Install pre-commit hooks
	pre-commit install

sync-deps: ## Sync requirements.txt from pyproject.toml
	pip-compile pyproject.toml -o requirements.txt
