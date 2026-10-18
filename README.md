# IT Asset Manager

Multi-site IT asset management (laptop / monitor / server / accessories), full lifecycle
from request to certified disposal. See **[DEVELOPMENT.md](DEVELOPMENT.md)** for the
development guide (conventions, data model, milestones).

## Quickstart (local)

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
docker compose -f docker-compose.dev.yml up -d db redis   # dev databases
make migrate && make seed
make run            # http://127.0.0.1:8000/admin/
```

- Remote workstation setup: [docs/remote-dev.md](docs/remote-dev.md)
- Production deploy: `docs/deploy-ubuntu.md` (§24)
