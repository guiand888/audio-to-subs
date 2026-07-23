.PHONY: help build test test-watch lint format typecheck quality clean run shell frontend-test frontend-install frontend-build frontend-dev frontend-shell version-check release

# Variables
IMAGE_NAME := parolesub
IMAGE_TAG := latest
PROD_IMAGE := $(IMAGE_NAME):$(IMAGE_TAG)

# Single source of truth for the app version (repo-root VERSION file).
APP_VERSION := $(shell cat VERSION 2>/dev/null)

# Backend dev tooling runs via `nix develop`; see flake.nix.
NIX_RUN := nix develop --command

help:  ## Show this help message
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-20s %s\n", $$1, $$2}'

build:  ## Build production container
	podman build -t $(PROD_IMAGE) .

version-check:  ## Verify VERSION is non-empty, (on a tagged commit) equals the git tag, and compose PAROLESUB_TAG fallbacks match
	@test -n "$(APP_VERSION)" || { echo "VERSION file is empty or missing"; exit 1; }
	@tag=$$(git describe --tags --exact-match 2>/dev/null); \
	if [ -n "$$tag" ] && [ "$$tag" != "$(APP_VERSION)" ]; then \
		echo "MISMATCH: git tag $$tag != VERSION=$(APP_VERSION)"; exit 1; \
	fi
	@stale=$$(grep -o 'PAROLESUB_TAG:-[^}]*' docker-compose.yml docker-compose.docker.yml 2>/dev/null \
		| sed 's/.*:-//' | sort -u); \
	for v in $$stale; do \
		if [ "$$v" != "$(APP_VERSION)" ]; then \
			echo "MISMATCH: compose PAROLESUB_TAG fallback=$$v != VERSION=$(APP_VERSION)"; \
			echo "Run 'make release VERSION=$(APP_VERSION)' to align, or edit docker-compose*.yml manually."; \
			exit 1; \
		fi; \
	done
	@echo "Version coherence OK ($(APP_VERSION))"

release:  ## Bump version (VERSION file + compose fallbacks): make release VERSION=v2.0.0-beta.11
	@test -n "$(VERSION)" || { echo "Usage: make release VERSION=vX.Y.Z"; exit 1; }
	@printf '%s\n' "$(VERSION)" > VERSION
	@sed -i 's|\$${PAROLESUB_TAG:-[^}]*}|\$${PAROLESUB_TAG:-$(VERSION)}|g' \
		docker-compose.yml docker-compose.docker.yml
	@echo ""
	@echo "VERSION is now $(VERSION) (the single source of truth; baked into the"
	@echo "package at build time from this file)."
	@echo "Compose PAROLESUB_TAG fallbacks updated to $(VERSION)."
	@echo "Next (run manually, IN THIS ORDER — the tag must be created AFTER"
	@echo "the commit it describes, otherwise it points at the wrong commit):"
	@echo "  git commit -am 'release: $(VERSION)'"
	@echo "  git tag -a $(VERSION) -m $(VERSION)"
	@echo "  git push --follow-tags"

test:  ## Run tests (nix develop)
	$(NIX_RUN) pytest

test-watch:  ## Run tests in watch mode (nix develop)
	$(NIX_RUN) pytest -f

test-cov:  ## Run tests with coverage report (nix develop)
	$(NIX_RUN) pytest --cov-report=html
	@echo "Coverage report: htmlcov/index.html"

lint:  ## Run linter (nix develop)
	$(NIX_RUN) ruff check audio_to_subs/ tests/

format:  ## Format code with black (nix develop)
	$(NIX_RUN) black audio_to_subs/ tests/

format-check:  ## Check code formatting (nix develop)
	$(NIX_RUN) black --check audio_to_subs/ tests/

typecheck:  ## Run type checker (nix develop)
	$(NIX_RUN) mypy audio_to_subs/

quality: format-check lint typecheck test  ## Run all quality checks

pre-commit-install:  ## Install pre-commit hooks (nix develop)
	$(NIX_RUN) pre-commit install

pre-commit-run:  ## Run pre-commit hooks on all files (nix develop)
	$(NIX_RUN) pre-commit run --all-files

clean:  ## Clean up containers and images
	podman container prune -f
	podman image prune -f

run:  ## Run production container (requires videos/ directory and Podman secret)
	podman run --rm \
		--userns=keep-id \
		--secret mistral_api_key,type=env,target=MISTRAL_API_KEY \
		-v ./videos:/input:ro,Z \
		-v ./subtitles:/output:Z \
		$(PROD_IMAGE) -i /input/sample.mp4 -o /output

shell:  ## Open a nix develop shell (backend + frontend toolchain)
	nix develop

compose-up:  ## Start services with Podman Compose (builds from the pinned GitHub tag, not this checkout)
	podman-compose up -d --build

compose-down:  ## Stop services with Podman Compose
	podman-compose down

compose-logs:  ## View logs from services
	podman-compose logs -f

compose-dev-up:  ## Start services with Podman Compose, building from this checkout
	podman-compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build

compose-dev-down:  ## Stop services started with compose-dev-up
	podman-compose -f docker-compose.yml -f docker-compose.dev.yml down

compose-dev-logs:  ## View logs from services started with compose-dev-up
	podman-compose -f docker-compose.yml -f docker-compose.dev.yml logs -f

secret-create:  ## Create Podman secret for API key (interactive)
	@read -p "Enter Mistral API Key: " api_key; \
	echo -n "$$api_key" | podman secret create mistral_api_key -

secret-list:  ## List Podman secrets
	podman secret ls

secret-rm:  ## Remove Mistral API key secret
	podman secret rm mistral_api_key

# Frontend targets — Node comes from the `frontend` nix devShell (flake.nix),
# never a host-installed toolchain.
FRONTEND_RUN := nix develop .\#frontend --command bash -c

frontend-test:  ## Run frontend tests (vitest)
	$(FRONTEND_RUN) "cd frontend && npm install && npm run test"

frontend-install:  ## Install frontend dependencies (generates package-lock.json)
	$(FRONTEND_RUN) "cd frontend && npm install"

frontend-build:  ## Build frontend for production (tsc + vite build)
	$(FRONTEND_RUN) "cd frontend && npm run build"

frontend-dev:  ## Start Vite dev server (proxies /api to localhost:8000)
	$(FRONTEND_RUN) "cd frontend && npm run dev -- --host"

frontend-shell:  ## Open a shell in the frontend nix devShell (for debugging npm issues)
	nix develop .#frontend

# WARNING: frontend-preview stubs auth and serves fake data.
# It is confined to dev by frontend/.dockerignore and must never
# be used as a production nginx config.
frontend-preview:  ## Serve the built frontend with stubbed auth (DEV ONLY — no backend needed)
	podman run --rm -p 8080:80 \
		-v ./frontend/dist:/usr/share/nginx/html:ro,Z \
		-v ./frontend/nginx.preview.conf:/etc/nginx/conf.d/default.conf:ro,Z \
		docker.io/library/nginx:1.30-alpine
