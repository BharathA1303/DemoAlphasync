# AlphaSync Academic — Deployment (ac.alphasync.app)

Internally-simulated tick-by-tick market data for users who do **not** connect a
broker. Runs as a **completely isolated** stack alongside two untouched
production apps on `147.93.168.157`.

- **Server dir:** `/opt/apps/alphasync-academic`  (the git repo is cloned here)
- **Compose project:** `acalphasync`
- **Domain:** `https://ac.alphasync.app`

---

## Isolation contract (audited collision-free)

| Resource | AlphaSync Academic | AlphaSync Real (brokerdemo) | TickAlpha |
|---|---|---|---|
| Compose project | `acalphasync` | brokerdemo | (its own) |
| Containers | `acalphasync-frontend/backend/pg/redis` | `brokerdemo-*` | `alphasync-api/postgres/redis` |
| Frontend port | **127.0.0.1:3004** | 127.0.0.1:3002 | — |
| Backend port | **127.0.0.1:8004** | 127.0.0.1:8002 | 8003 |
| Postgres/Redis host port | **none** | none | — |
| Network | `acalphasync_acalphasync-net` | `brokerdemo_brokerdemo-net` | separate |
| Volumes | `acalphasync_acalphasync-pgdata / -redis / -uploads` | `brokerdemo_*` | separate |

Volume/network names come out as `acalphasync_<name>` because the compose file
leaves them unpinned under project `acalphasync` — exactly the required form.

### Hard safety guarantees (built into every script + the workflow)
- **Never** `docker system/volume/network prune`.
- **Never** `docker rm`, `docker stop`, or `docker compose down`.
- **Never** `--remove-orphans`.
- **Never** touches `brokerdemo-*` or TickAlpha containers/volumes/networks/nginx.
- Pre-deploy **aborts** if 3004 or 8004 is occupied by anything that isn't our
  own project — it will *not* free a port by killing another app.
- All `docker compose` commands are scoped with `-p acalphasync`.

---

## Files

| File | Purpose |
|---|---|
| `docker-compose.yml` | project `acalphasync`, ports 3004/8004, no host port for pg/redis |
| `.env.academic.example` | env template → copy to `.env` on the server |
| `deploy/nginx/ac.alphasync.app.conf` | vhost → 3004/8004 (this site only) |
| `deploy/scripts/deployment.sh` | first deploy + port guard + verify |
| `deploy/scripts/update.sh` | `git fetch → reset --hard → build → up -d` |
| `deploy/scripts/rollback.sh` | revert this app only (data preserved) |
| `deploy/scripts/verify.sh` | read-only post-deploy check of all 11 containers |
| `.github/workflows/deploy-academic.yml` | CI deploy to `/opt/apps/alphasync-academic` |

---

## One-time server setup

```bash
sudo mkdir -p /opt/apps
sudo git clone <REPO_URL> /opt/apps/alphasync-academic
cd /opt/apps/alphasync-academic

cp .env.academic.example .env
nano .env                       # set POSTGRES_PASSWORD, JWT_SECRET, etc.
chmod +x deploy/scripts/*.sh

# DNS: A record  ac.alphasync.app → 147.93.168.157

# Nginx (this site only — never edits demo.alphasync.app or TickAlpha):
sudo cp deploy/nginx/ac.alphasync.app.conf /etc/nginx/sites-available/ac.alphasync.app.conf
sudo ln -sfn /etc/nginx/sites-available/ac.alphasync.app.conf \
             /etc/nginx/sites-enabled/ac.alphasync.app.conf
sudo certbot certonly --nginx -d ac.alphasync.app
sudo nginx -t && sudo systemctl reload nginx

# Deploy:
./deploy/scripts/deployment.sh
```

## CI/CD

`.github/workflows/deploy-academic.yml` SSHes in and runs, inside
`/opt/apps/alphasync-academic`:

```
git fetch  →  git reset --hard origin/main  →  docker compose build  →  docker compose up -d  →  verify
```

Required repo secrets: `ACADEMIC_SSH_HOST` (147.93.168.157), `ACADEMIC_SSH_USER`,
`ACADEMIC_SSH_KEY`, `ACADEMIC_SSH_PORT` (22).

---

## Expected `docker ps` after deploy (all must be running)

```
brokerdemo-frontend   brokerdemo-backend   brokerdemo-pg   brokerdemo-redis      ← untouched
alphasync-api         alphasync-postgres   alphasync-redis                       ← untouched
acalphasync-frontend  acalphasync-backend  acalphasync-pg  acalphasync-redis     ← this deploy
```

`deploy/scripts/verify.sh` asserts exactly this and is run automatically at the
end of every deploy/update.

## Day-2

| Task | Command (from `/opt/apps/alphasync-academic`) |
|---|---|
| Deploy | `./deploy/scripts/deployment.sh` |
| Update | `./deploy/scripts/update.sh` |
| Rollback (images) | `./deploy/scripts/rollback.sh` |
| Rollback (commit) | `./deploy/scripts/rollback.sh --git` |
| Verify | `./deploy/scripts/verify.sh` |
| Logs | `docker compose -p acalphasync logs -f backend` |
