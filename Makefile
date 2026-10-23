# hcwave – common developer and operator commands. `make help` lists them.
SHELL := /bin/bash
ENV ?= dev
CHART := deploy/helm/hcwave

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

# ---- Local development -------------------------------------------------------
.PHONY: env up down logs simulate
env: ## Create .env from the template (first run)
	@test -f .env || cp .env.example .env && echo ".env ready"
up: env ## Start the full stack locally (docker compose)
	docker compose up --build -d && docker compose ps
down: ## Stop the local stack
	docker compose down
logs: ## Follow API and worker logs
	docker compose logs -f api worker
simulate: ## Send "hi" as a patient to the local assistant
	curl -s -XPOST localhost:8000/dev/simulate -H 'content-type: application/json' -d '{"text":"hi"}' | python3 -m json.tool

# ---- Quality ---------------------------------------------------------------------
.PHONY: lint test ui-build validate
lint: ## Lint backend and functions (ruff, Google style)
	cd services/backend && ruff check src tests migrations && ruff format --check src tests migrations
	cd services/functions && ruff check .
test: ## Backend tests (needs TEST_DATABASE_URL or local Postgres)
	cd services/backend && pytest -q
ui-build: ## Type-check and build the staff UI
	cd services/staff-ui && npm ci && npm run build
validate: ## Bicep build + Helm lint/template
	az bicep build --file infra/bicep/main.bicep --stdout > /dev/null
	helm lint $(CHART) -f $(CHART)/values-local.yaml
	helm template hcwave $(CHART) -f $(CHART)/values-local.yaml > /dev/null

# ---- Azure -------------------------------------------------------------------------
.PHONY: infra-whatif infra entra addons db-bootstrap deploy workflows
infra-whatif: ## Preview infrastructure changes (ENV=dev|staging|prod)
	scripts/deploy-infra.sh $(ENV) --what-if
infra: ## Deploy infrastructure with Bicep
	scripts/deploy-infra.sh $(ENV)
entra: ## Create Entra app registrations (UI_URL=https://staff.example)
	scripts/entra-apps.sh $(ENV) $(UI_URL)
addons: ## Install ALB controller (+ cert-manager) into AKS
	scripts/install-cluster-addons.sh $(ENV) --with-cert-manager
db-bootstrap: ## Create the workload identity role in PostgreSQL
	scripts/db-bootstrap.sh $(ENV)
deploy: ## Build images in ACR and deploy the Helm chart
	scripts/deploy-app.sh $(ENV)
workflows: ## Deploy Logic Apps workflows and Durable Functions
	scripts/deploy-workflows.sh $(ENV)

# ---- Documentation -----------------------------------------------------------------
.PHONY: docs
docs: ## Regenerate the as-built Word document
	cd docs/generator && npm ci && node build.cjs
