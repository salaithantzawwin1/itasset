# IT Asset Manager

Multi-site IT asset management system for Ubuntu servers.

## Quick Start

```bash
# 1. Clone
git clone <repo-url> itasset && cd itasset

# 2. Python env
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 3. Environment
cp .env.example .env

# 4. Database
docker compose -f docker-compose.dev.yml up -d db redis
make migrate
make seed

# 5. Run
make run          # http://127.0.0.1:8000
```

Admin account: `make superuser`

## Documentation

| Doc | Purpose |
|---|---|
| DEVELOPMENT.md | Development guide |
| docs/PROGRESS.md | Current milestone status |
| docs/category-schema-design.md | Category-specific fields |
| GLOSSARY.md | Term definitions |
| CHANGELOG.md | Version history |

## Tech Stack

- Python 3.12 · Django 5.1 · PostgreSQL 16
- Celery + Redis · Docker + Nginx
- LDAP/AD authentication

## Scale Target

10,000–100,000 assets · multiple sites · 100+ users.

## Contributing

1. Read DEVELOPMENT.md first
2. Branch: feat/, fix/, chore/
3. make lint && make test must pass
4. Open a PR — one concern per PR
5. Include migration + tests + docs

## License

Internal use only.

---

**End of Document**