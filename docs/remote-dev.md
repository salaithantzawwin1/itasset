# Remote Development over SSH — Installation & Configuration Guide

**Target:** `192.168.100.142` (Ubuntu Server)
**Goal:** edit, run, and test the IT Asset Manager from your laptop while the code,
virtualenv, and databases all live on the server — one `ssh` connection away.

> Relationship to other docs: `DEVELOPMENT.md` §7 describes **local** setup.
> This guide is the **remote** variant of the same steps. Production deployment is a
> different thing entirely — see `docs/deploy-ubuntu.md` (DEVELOPMENT.md §24).

---

## 1. Can we do development by SSHing in? — Yes

Three options; this guide implements **Option A** (recommended):

| Option | How | Pros | Cons |
|---|---|---|---|
| **A — Remote IDE (this guide)** | Repo + venv + Docker **on the server**; VS Code Remote-SSH edits it | server == dev env, laptop stays light, no local Docker needed | needs decent server specs |
| B — Terminal only | Repo on server; plain `ssh` terminal + vim/nano | zero install on laptop | no IDE features |
| C — Repo local, run remote | Edit locally, `rsync`/mount to server | best laptop tooling | sync friction; env drift |

```
[Laptop]                          [192.168.100.142 — Ubuntu Server]
VS Code + Remote-SSH  ── SSH 22 ──▶  ~/itasset  (repo + .venv)
browser ── http://192.168.100.142:8000 ──▶  make run (Django)
                                   docker: postgres, redis
```

**Verified:** TCP port 22 on 192.168.100.142 accepts connections (reachability check OK).

---

## 2. Prerequisites

- Laptop: VS Code (or Cursor), `ssh` client, network access to `192.168.100.0/24`
- Server: Ubuntu **24.04 LTS** (recommended; 22.04 works with a Python note below),
  a sudo-capable user (example: `dev`), static IP `192.168.100.142`
- Repo access (Git URL + credentials or deploy key)

---

## 3. Server Preparation

Log in once with the initial credentials (or console):

```bash
ssh dev@192.168.100.142

# base packages
sudo apt update && sudo apt -y full-upgrade
sudo apt -y install build-essential git curl ca-certificates \
    python3.12 python3.12-venv python3-pip make tmux ufw fail2ban unattended-upgrades
python3.12 --version    # Ubuntu 24.04 ships 3.12 (DEVELOPMENT.md §5)
```

> **Ubuntu 22.04:** ships Python 3.10. Either use `python3` (and update tooling) or add
> the deadsnakes PPA for 3.12. Prefer upgrading the server to 24.04 LTS.

### Docker (for dev databases — postgres/redis)

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker "$USER"     # then log out and back in
newgrp docker
docker compose version              # must print a version
```

> ⚠️ Membership in the `docker` group is **root-equivalent**. Acceptable on a
> LAN dev server; on shared/production hosts use `sudo docker` instead of the group.

### Keep it patched

```bash
sudo dpkg-reconfigure -plow unattended-upgrades   # auto security updates ON
```

---

## 4. SSH Key Authentication & Hardening

### 4.1 Key that is now in use (laptop ↔ server)

An ed25519 machine key was created in M1 and its public half installed on the
server (1 entry in `~/.ssh/authorized_keys`):

| Property | Value |
|---|---|
| type | ed25519, no passphrase — protect later with `ssh-keygen -p` |
| private key (laptop) | `~/.ssh/id_rsa_glg` |
| public key (server) | `~/.ssh/authorized_keys` on 192.168.100.142 |
| host alias | `itasset-dev` (see §4.3) |

Verify from the laptop:

```bash
ssh -i ~/.ssh/id_rsa_glg 192.168.100.142 'echo login-ok'   # prints login-ok
```

### 4.2 Hardening already applied on the server (root, 2026-10-12)

`/etc/ssh/sshd_config` now contains:

```
PasswordAuthentication no
PubkeyAuthentication yes
PermitRootLogin no
```

Verified by forcing password-only auth — the server now **denies** it:

```bash
# this is denied now:
ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no glgadmin@192.168.100.142 'echo X'

# key login works:
ssh -i ~/.ssh/id_rsa_glg glgadmin@192.168.100.142 'echo login-ok'
```

- To add a second key (another laptop): on that laptop run `ssh-keygen -t ed25519`,
  then `cat ~/.ssh/id_ed25519.pub | ssh -i ~/.ssh/id_rsa_glg 192.168.100.142 'cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys'`.
- Keep one recovery session open when toggling hardening (DEVELOPMENT.md §11).

### 4.3 Named host on the laptop — ~/.ssh/config

```config
Host itasset-dev
    HostName 192.168.100.142
    User glgadmin
    IdentityFile ~/.ssh/id_rsa_glg
    IdentitiesOnly yes
    ServerAliveInterval 60
    ServerAliveCountMax 3
```

```bash
chmod 600 ~/.ssh/config
ssh itasset-dev        # key used automatically; no password
```

---

## 5. Development Environment on the Server

Mirrors DEVELOPMENT.md §7 — only the machine changes:

```bash
ssh itasset-dev
git clone <repo> ~/itasset && cd ~/itasset

python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
docker compose -f docker-compose.dev.yml up -d db redis

make migrate
make seed                 # demo data — dev only (DEVELOPMENT.md §19)
make test                 # full suite must pass before you start
```

Optional quality-of-life:

```bash
echo "source ~/itasset/.venv/bin/activate" >> ~/.bashrc   # auto-activate
```

---

## 6. VS Code Remote-SSH Setup (laptop)

1. Install the **Remote - SSH** extension (`ms-vscode-remote.remote-ssh`).
2. `Ctrl+Shift+P` → **Remote-SSH: Connect to Host…** → `itasset-dev`.
3. **File → Open Folder…** → `/home/dev/itasset`.
4. Install project extensions **on the remote side** (they prompt "Install in SSH: …"):
   - Python, Ruff (matches §8 lint rules), Docker, GitLens (optional).
5. Settings that must be **remote** (`.vscode/settings.json` in the repo):

```json
{
  "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python",
  "[python]": { "editor.formatOnSave": true, "editor.defaultFormatter": "charliermarsh.ruff" },
  "python.analysis.typeCheckingMode": "basic"
}
```

Done — the integrated terminal, debugger, and test runner all run **on the server**.

**No VS Code?** plain SSH + `tmux` works: `ssh itasset-dev -t 'tmux attach -t dev || tmux new -s dev'`.

---

## 7. Running the Dev Server — how the laptop sees it

Two safe ways (pick one):

### Option 1 — SSH tunnel (recommended; nothing is exposed on the network)

```bash
# laptop: keep a tunnel open alongside your VS Code session
ssh -N -L 8000:127.0.0.1:8000 itasset-dev
# then open http://127.0.0.1:8000 on the laptop
```

### Option 2 — bind on the LAN

```bash
# server: run Django bound to the LAN interface
make run   # with runserver 0.0.0.0:8000 (set RUNHOST=0.0.0.0 in .env)
# laptop: http://192.168.100.142:8000
```

Whichever you choose, long-running processes go inside **tmux** so they survive
disconnects:

```bash
tmux new -s dev          # run `make run` here
tmux new -s worker       # run `make worker` here
tmux ls ; tmux attach -t dev      # detach: Ctrl-b d
```

---

## 8. Firewall & Ongoing Security (server)

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH
sudo ufw allow from 192.168.100.0/24 to any port 22 proto tcp   # LAN only, optional
sudo ufw enable && sudo ufw status verbose

sudo systemctl enable --now fail2ban        # brute-force protection
```

Rules to keep (from DEVELOPMENT.md §22):

- [ ] Keys only — `PasswordAuthentication no`, no root login
- [ ] `.env` and secrets never committed; edit `.env` **on the server** only
- [ ] `DEBUG=0` outside local experiments; `ALLOWED_HOSTS` explicit
- [ ] Auto security updates enabled; `sudo apt update` weekly
- [ ] Laptop key passphrase-protected (or hardware key); revoke lost keys from
      `~/.ssh/authorized_keys` immediately
- [ ] Docker group membership acknowledged as root-equivalent (§3)

---

## 9. Verification Checklist

Run once after setup; every box must pass:

- [ ] `ssh itasset-dev` logs in **without a password**
- [ ] `ssh itasset-dev 'python3.12 --version && docker compose version'` prints both
- [ ] VS Code connects and opens `/home/dev/itasset` (status bar shows **SSH: itasset-dev**)
- [ ] Integrated terminal auto-activates `.venv`
- [ ] `make lint && make test` passes **on the server**
- [ ] `docker compose -f docker-compose.dev.yml ps` shows `db` + `redis` healthy
- [ ] Dev server reachable from the laptop (tunnel or LAN URL) — login page renders
- [ ] `tmux` session survives closing the laptop lid / dropping Wi-Fi
- [ ] `sudo ufw status` = active; `sudo fail2ban-client status sshd` = running

---

## 10. Troubleshooting

| Symptom | Fix |
|---|---|
| `Permission denied (publickey)` | server: `ls -l ~/.ssh` → dir `700`, `authorized_keys` `600`, owner correct; check `AllowUsers` in §4.2 |
| `ssh: connect to host … port 22: Connection refused` | `sudo systemctl status ssh`; check `ufw status` |
| VS Code: "Failed to connect" | laptop: `ssh -v itasset-dev`; confirm `HostName`/`User` in `~/.ssh/config` |
| `docker: permission denied` | re-login after `usermod -aG docker` (or use `sudo docker`) |
| `python3.12: command not found` | wrong Ubuntu version — see §3 note (22.04) |
| Django not reachable from laptop | check bind address (§7) and `ALLOWED_HOSTS` |
| Terminal freezes after idle | `ServerAliveInterval 60` already set; also run work in `tmux` |
| `make test` fails only on server | DB not up: `docker compose -f docker-compose.dev.yml ps` |
| Slow large-file search in VS Code | exclude `.venv/`, `static/` in remote VS Code settings |

---

## 11. Daily Workflow Summary

```bash
ssh itasset-dev                       # or click the host in VS Code
cd ~/itasset && source .venv/bin/activate
git pull && make lint && make test    # before starting work
tmux attach -t dev                    # dev server already running
# ... edit in VS Code (running remotely) ...
git checkout -f feat/<name>           # branch per DEVELOPMENT.md §21
# commit + push, open PR — CI runs ruff + pytest (§21)
```

Everything in DEVELOPMENT.md (conventions §8, testing §20, git §21, DoD §29) applies
unchanged — only **where** the commands run has changed: on `192.168.100.142`.

---

## 12. Field notes — verified setup on 192.168.100.142 (2026-10-12)

### Actual server environment (recon)

| Item | Value |
|---|---|
| OS | Ubuntu 22.04.5 LTS (kernel 5.15) |
| User | `glgadmin` (sudo group) |
| CPU / RAM | 2 cores / 3.8 GiB (~3.2 GiB free) |
| Disk | 490 GB (~462 GB free, 2% used) |
| Python | 3.10.12 only — **no 3.12** |
| Docker / make | **not installed** (apt candidates available) |
| git / tmux | 2.34.1 / 3.2a |
| Internet | PyPI + Ubuntu archive reachable |
| SSH | key auth **active** — password auth disabled on server (§4.2) |

### What runs now (root-less dev path)

Installing packages needs admin rights, so M1 was completed **without root**:

| Step | How |
|---|---|
| venv + pip | `python3 -m venv --without-pip .venv` + `get-pip.py` (ensurepip missing) |
| dependencies | `pip install -e ".[dev]"` → Django 5.2.18 on Python 3.10 |
| **PostgreSQL 16.2** | user-space binaries from `pip install pgserver`; data `~/pgdata_itasset`; TCP `127.0.0.1:5433` |
| `.env` | `DATABASE_URL=postgresql://itasset@127.0.0.1:5433/itasset` |
| migrate + seed | migrations `people`, `assets`; 50 demo assets, 3 sites, 3 people |
| admin | superuser `admin` (dev-only password — **change it**) |
| tests | `pytest -q` → **3 passed** |
| server | `runserver 0.0.0.0:8000` via nohup → `~/itasset/runserver.log` |

### Verified end-to-end (from the laptop, over LAN)

- `GET /healthz` → `{"status": "ok", "db": "ok"}`
- `GET /admin/login/` → 200
- admin login POST → 302 + session cookie; dashboard **200**; asset changelist **200**
  listing seeded tags (`IT-HW-DSK-0002`, …)

### After a server reboot

```bash
BIN=~/itasset/.venv/lib/python3.10/site-packages/pgserver/pginstall/bin
"$BIN/pg_ctl" -D ~/pgdata_itasset -l ~/pgdata_itasset/server.log \
  -o "-p 5433 -c listen_addresses=127.0.0.1 -k /tmp" -w start
cd ~/itasset && nohup .venv/bin/python manage.py runserver 0.0.0.0:8000 > runserver.log 2>&1 &
```

### Still pending — needs admin rights (one command on the server)

```bash
bash scripts/server-bootstrap.sh        # make, docker + compose, python3.12, ufw/fail2ban
cd ~/itasset && docker compose -f docker-compose.dev.yml up -d db redis
```

After that, the setup matches §5 of this guide exactly (compose `db` on 5432 replaces
the user-space postgres on 5433 — update `DATABASE_URL` when switching).

### Deviations from this guide / DEVELOPMENT.md

- Python **3.10** instead of §5's 3.12 — Django 5.2 supports 3.10; bootstrap installs 3.12.
- Dev DB = user-space PostgreSQL 16.2 instead of compose `db` — same engine, other launch.
- `make` targets run as raw commands (`make` binary arrives with the bootstrap).
- Ubuntu 22.04 instead of §5's 24.04 — still LTS (until 2027); upgrade optional.
