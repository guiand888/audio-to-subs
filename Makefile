.PHONY: help build build-dev test test-watch lint format typecheck quality clean run shell

# Variables
IMAGE_NAME := audio-to-subs
IMAGE_TAG := latest
DEV_IMAGE := $(IMAGE_NAME):dev
PROD_IMAGE := $(IMAGE_NAME):$(IMAGE_TAG)

help:  ## Show this help message
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'

build:  ## Build production container
	podman build -t $(PROD_IMAGE) .

build-dev:  ## Build development container
	podman build -t $(DEV_IMAGE) -f Dockerfile.dev .

test:  ## Run tests in container
	podman run --rm -v ./:/app:Z $(DEV_IMAGE) pytest

test-watch:  ## Run tests in watch mode
	podman run --rm -it -v ./:/app:Z $(DEV_IMAGE) pytest -f

test-cov:  ## Run tests with coverage report
	podman run --rm -v ./:/app:Z $(DEV_IMAGE) pytest --cov-report=html
	@echo "Coverage report: htmlcov/index.html"

lint:  ## Run linter
	podman run --rm -v ./:/app:Z $(DEV_IMAGE) ruff check src/ tests/

format:  ## Format code with black
	podman run --rm -v ./:/app:Z $(DEV_IMAGE) black src/ tests/

format-check:  ## Check code formatting
	podman run --rm -v ./:/app:Z $(DEV_IMAGE) black --check src/ tests/

typecheck:  ## Run type checker
	podman run --rm -v ./:/app:Z $(DEV_IMAGE) mypy src/

quality: format-check lint typecheck test  ## Run all quality checks

pre-commit-install:  ## Install pre-commit hooks in container
	podman run --rm -it -v ./:/app:Z $(DEV_IMAGE) pre-commit install

pre-commit-run:  ## Run pre-commit hooks on all files
	podman run --rm -v ./:/app:Z $(DEV_IMAGE) pre-commit run --all-files

clean:  ## Clean up containers and images
	podman container prune -f
	podman image prune -f

run:  ## Run production container (requires videos/ directory and Podman secret)
	podman run --rm \
		--secret mistral_api_key \
		-v ./videos:/input:ro \
		-v ./subtitles:/output \
		$(PROD_IMAGE) -i /input/sample.mp4 -o /output

shell:  ## Open shell in development container
	podman run --rm -it -v ./:/app:Z $(DEV_IMAGE) /bin/sh

compose-up:  ## Start services with Podman Compose
	podman-compose up

compose-down:  ## Stop services with Podman Compose
	podman-compose down

compose-logs:  ## View logs from services
	podman-compose logs -f

secret-create:  ## Create Podman secret for API key (interactive)
	@read -p "Enter Mistral API Key: " api_key; \
	echo "$$api_key" | podman secret create mistral_api_key -

secret-list:  ## List Podman secrets
	podman secret ls

secret-rm:  ## Remove Mistral API key secret
	podman secret rm mistral_api_key
