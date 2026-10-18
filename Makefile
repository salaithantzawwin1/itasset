PY ?= python
MANAGE = $(PY) manage.py

.PHONY: lint format test migrate seed run shell createsuperuser worker openapi import audit-deps backup

lint:
	ruff check . && ruff format --check .

format:
	ruff check --fix . && ruff format .

audit-deps:  ## Vulnerability scan of installed deps (gap §4 workstream 11)
	$(PY) -m pip_audit --progress-spinner off

backup:  ## DB dump + attachments archive (§12.3; runbook docs/runbooks/backup-restore.md)
	bash deploy/backup.sh

test:
	pytest -q

migrate:
	$(MANAGE) makemigrations && $(MANAGE) migrate

seed:
	$(MANAGE) seed_demo

run:
	$(MANAGE) runserver 0.0.0.0:8000

shell:
	$(MANAGE) shell

createsuperuser:
	$(MANAGE) createsuperuser

worker:
	celery -A config worker -l info

openapi:
	$(MANAGE) spectacular --file docs/openapi.yaml

# make import FILE=assets.csv          → dry-run preview (§13)
# make import FILE=assets.csv COMMIT=1 → write rows + ActivityLog
import:
	$(MANAGE) import_csv $(FILE) $(if $(COMMIT),--commit,)
