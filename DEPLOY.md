# AlphaSync — Contabo VPS Deployment Guide

> **Reference**: See [ARCHITECTURE.md](./ARCHITECTURE.md) for full system documentation.  
> **Stack**: FastAPI backend · React 18 frontend · PostgreSQL 16 · Redis 7 · Docker Compose

## Prerequisites

- A Contabo VPS (Ubuntu 22.04 or 24.04 recommended, minimum 2 vCPU / 4GB RAM)
- Domain `alphasync.app` + `www.alphasync.app` pointing to your server's IP (A records in DNS)
- SSH access to the server as root

---

## Step 1: Initial Server Setup

From your **local machine**, run the setup script against the server:

```bash
ssh root@YOUR_SERVER_IP 'bash -s' < deploy/setup-server.sh
```

This installs Docker, creates a `deploy` user, configures UFW firewall (SSH/HTTP/HTTPS only), installs fail2ban, and creates 2GB swap.

After this, SSH in as the deploy user:

```bash
ssh deploy@YOUR_SERVER_IP
```

---

## Step 2: Upload the Project

From your **local machine**, copy the project to the server:

```bash
# Option A: Git clone (recommended)
ssh deploy@YOUR_SERVER_IP "git clone https://github.com/netguy001/alphasync.git /opt/alphasync"

# Option B: rsync from local
rsync -avz --exclude node_modules --exclude __pycache__ --exclude .git \
  ./ deploy@YOUR_SERVER_IP:/opt/alphasync/
```

---

## Step 3: Configure Environment Variables

On the **server**:

```bash
cd /opt/alphasync

# Copy the production env template
cp deploy/.env.production .env

# Edit and fill in your secrets
nano .env
```

**You MUST change these values:**

| Variable | How to generate |
|---|---|
| `POSTGRES_PASSWORD` | `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `REDIS_PASSWORD` | `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `BROKER_ENCRYPTION_KEY` | `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` |

Also fill in your Zebu/MYNT API credentials (`ZEBU_API_SECRET`, `ZEBU_VENDOR_CODE`).

**Firebase Setup:**

1. Download your Firebase service account JSON from Firebase Console → Project Settings → Service Accounts
2. Place it on the server at `/opt/alphasync/firebase-credentials.json`
3. For the frontend build, set these in `.env`:
   - `VITE_FIREBASE_API_KEY`
   - `VITE_FIREBASE_AUTH_DOMAIN`
   - `VITE_FIREBASE_PROJECT_ID`
   - `VITE_FIREBASE_STORAGE_BUCKET`
   - `VITE_FIREBASE_MESSAGING_SENDER_ID`
   - `VITE_FIREBASE_APP_ID`

---

## Step 4: Build and Start Services

**Option A — Build images locally on the server:**

```bash
cd /opt/alphasync

# Build backend image
docker build -t ghcr.io/netguy001/alphasync-backend:latest ./backend

# Build frontend image
docker build -t ghcr.io/netguy001/alphasync-frontend:latest ./frontend

# Run the first deploy script
bash deploy/first-deploy.sh
```

**Option B — Pull pre-built images from GHCR** (if you have CI/CD pushing images):

```bash
cd /opt/alphasync
bash deploy/first-deploy.sh
```

The first-deploy script will:
1. Validate your `.env` secrets
2. Pull/start PostgreSQL and Redis
3. Start the backend and run Alembic database migrations
4. Start the frontend and nginx

---

## Step 5: Setup SSL (HTTPS)

SSL is managed by **CloudPanel**, not Docker containers.

1. Log in to CloudPanel at `https://YOUR_SERVER_IP:8443`
2. Add site: `www.alphasync.app` (with `alphasync.app` as alias)
3. Set reverse proxy origin to `127.0.0.1:3000`
4. Click "Issue Let's Encrypt Certificate"
5. Add a second reverse proxy rule for `/api/*` → `127.0.0.1:8000` and `/ws/*` → `127.0.0.1:8000` (WebSocket upgrade)

CloudPanel auto-renews certificates via cron.

After this, your site is live at **https://www.alphasync.app**

---

## Step 6: Reset stale market cache

If market prices or charts look poisoned after a bad session, clear the Redis market cache before restarting the backend worker:

```bash
python3 /opt/alphasync/backend/tools/reset_market_cache.py
```

This removes price, history, ticker, indices, commodities, snapshot, and provider-status cache entries so fresh Zebu data can repopulate Redis.

---

## Step 7: Verify

```bash
# Check all containers are running
docker compose -f docker-compose.prod.yml ps

# Check backend health
curl -s http://localhost:8000/api/health | python3 -m json.tool

# Check logs if something is wrong
docker compose -f docker-compose.prod.yml logs backend --tail 50
docker compose -f docker-compose.prod.yml logs frontend --tail 50
docker compose -f docker-compose.prod.yml logs db --tail 50
```

---

## Updating the Application

After pushing new code:

```bash
cd /opt/alphasync

# Pull latest code
git pull

# Rebuild images
docker build -t ghcr.io/netguy001/alphasync-backend:latest ./backend
docker build -t ghcr.io/netguy001/alphasync-frontend:latest ./frontend

# Run migrations and restart
docker compose -f docker-compose.prod.yml up -d backend
docker compose -f docker-compose.prod.yml exec backend alembic upgrade head
docker compose -f docker-compose.prod.yml up -d
```

---

## Useful Commands

```bash
# View all logs
docker compose -f docker-compose.prod.yml logs -f

# Restart a specific service
docker compose -f docker-compose.prod.yml restart backend

# Enter the backend container
docker compose -f docker-compose.prod.yml exec backend bash

# Run Alembic migrations manually
docker compose -f docker-compose.prod.yml exec backend alembic upgrade head

# Connect to PostgreSQL
docker compose -f docker-compose.prod.yml exec db psql -U alphasync

# Stop everything
docker compose -f docker-compose.prod.yml down

# Stop everything AND delete data (DANGEROUS)
docker compose -f docker-compose.prod.yml down -v

# View disk usage
docker system df
```

---

## Architecture (Production)

```
Internet
  │
  ▼
┌─────────────────────┐
│  CloudPanel Nginx    │  ← SSL termination, reverse proxy
│  (:80/443)           │
└────┬────┬───────────┘
     │    │
     ▼    ▼
┌────────┐ ┌──────────┐
│Frontend│ │ Backend  │
│ :3000  │ │ :8000    │  ← gunicorn + 1 uvicorn worker (single-process async)
└────────┘ └──┬───┬───┘
              │   │
              ▼   ▼
         ┌──────┐ ┌───────┐
         │ PG16 │ │ Redis │
         │:5432 │ │ :6379 │
         └──────┘ └───────┘
```

CloudPanel manages Nginx externally. Docker services (backend, frontend, db, redis) are on an internal Docker network. Only backend (:8000) and frontend (:3000) are exposed on localhost for CloudPanel to proxy.
