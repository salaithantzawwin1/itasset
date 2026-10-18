# IT Asset Manager — Makefile
# See DEVELOPMENT.md §31

.PHONY: help install env up-db down-db reset-db run worker beat shell dbshell \
        migrate makemigrations showmigrations seed superuser \
        lint format test test-fast audit check-deploy \
        build up collectstatic openapi backup restore import export version

help:  ## List all targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

install:  ## Create venv + install deps
	python3.12 -m venv .venv
	. .venv/bin/activate && pip install -e ".[dev]"

env:  ## Copy .env.example -> .env if missing
	@test -f .env || cp .env.example .env

up-db:  ## Start dev DB + Redis
	docker compose -f docker-compose.dev.yml up -d db redis

down-db:  ## Stop dev DB + Redis
	docker compose -f docker-compose.dev.yml down

run:  ## Run dev server
	python manage.py runserver 0.0.0.0:8000

worker:  ## Celery worker
	celery -A config worker -l info

beat:  ## Celery beat
	celery -A config beat -l info

shell:  ## Django shell
	python manage.py shell

dbshell:  ## psql into dev DB
	docker compose -f docker-compose.dev.yml exec db psql -U postgres

migrate:  ## makemigrations + migrate
	python manage.py makemigrations
	python manage.py migrate

makemigrations:  ## makemigrations only
	python manage.py makemigrations

showmigrations:  ## List migration state
	python manage.py showmigrations

seed:  ## Load demo data (dev only)
	python manage.py seed_demo

superuser:  ## Create admin user
	python manage.py createsuperuser

lint:  ## ruff check + format check
	ruff check .
	ruff format --check .

format:  ## Auto-fix lint/format
	ruff check --fix .
	ruff format .

test:  ## Full test suite with coverage
	pytest -q --cov=apps --cov-report=term-missing

test-fast:  ## Fast test (stop on first failure)
	pytest -q -x

audit:  ## Dependency CVE scan
	pip-audit

check-deploy:  ## Django deploy check
	python manage.py check --deploy

build:  ## Build Docker images
	docker compose build

up:  ## Start prod stack
	docker compose up -d

collectstatic:  ## Collect static files
	python manage.py collectstatic --noinput

openapi:  ## Regenerate OpenAPI schema
	python manage.py spectacular --file docs/openapi.yaml

backup:  ## Run backup script
	./scripts/backup.sh

restore:  ## Restore from snapshot (SNAP=path)
	@read -p "Restore from $(SNAP)? [y/N] " ans; [ "$$ans" = "y" ] && \
		./scripts/restore.sh $(SNAP)

import:  ## Bulk asset import (FILE=x.csv)
	python manage.py import_csv $(FILE)

export:  ## Export a report (SLUG=inventory)
	python manage.py export_report $(SLUG)

version:  ## Print version info
	@echo "App:     $$(git describe --tags --always 2>/dev/null || echo 'dev')"
	@echo "Python:  $$(python --version 2>&1)"
	@echo "Git SHA: $$(git rev-parse --short HEAD 2>/dev/null || echo 'unknown')"