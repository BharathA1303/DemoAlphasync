# AlphaSync — Virtual Stock Trading Platform

**Practice stock trading with ₹10,00,000 virtual money. Zero risk. Real-time market data via Zebu/MYNT, Alice Blue, or Zerodha.**

[Live Demo](https://demo.alphasync.app) | [Production](https://www.alphasync.app)

---

## 📖 What is AlphaSync?

AlphaSync is a **virtual (paper) trading platform** for the Indian stock market — a flight simulator for trading stocks, futures, and options.

- **₹10,00,000 virtual capital** when you sign up — completely free
- **Buy and sell real Indian stocks** (NIFTY 50, SENSEX, etc.) using **real-time market prices** streamed from broker WebSocket feeds
- **Futures trading** — NSE equity and index futures (NIFTY, BANKNIFTY, FINNIFTY, etc.) with full F&O simulation
- **Options chain data** — Live NSE option chain with greeks (Delta, Gamma, Theta, Vega, IV)
- **Commodities** — MCX/NCDEX commodities (GOLD, SILVER, CRUDEOIL, etc.)
- **ZeroLoss Strategy / Auto-Alpha** — Proprietary strategy using 6-factor confidence scoring that targets break-even exits on losing trades
- **Automated algo trading** — Create trading bots using SMA, RSI, MACD, and 16+ strategies
- **AI Mentor (Grok-powered)** — AI-driven trading assistant and market tutor
- **Leaderboard** — Ranked performance among all users
- **Multi-broker support** — Connect your Zebu/MYNT, Alice Blue, or Zerodha account
- **Firebase Authentication** — Email/password, Google sign-in, email verification, phone collection
- **Admin panel** — User management, audit logs, runtime flags, 2FA security, bug report management
- **Zero financial risk** — Virtual money with real-market experience

**Who is it for?**
- 🎓 **Students** learning how the stock market works
- 📈 **Beginners** who want to practice before investing real money
- 🤖 **Traders** who want to test automated strategies safely
- 👨‍🏫 **Instructors** teaching finance and trading

---

## 🗂️ Application Pages

| Route | Page | Description |
|-------|------|-------------|
| `/` or `/login` | LoginPage | Firebase auth: email/password + Google sign-in |
| `/register` | LoginPage | Registration flow (shared with LoginPage) |
| `/verify-email` | VerifyEmailPage | Email verification gate |
| `/collect-phone` | CollectPhonePage | Post-registration phone collection |
| `/account-status` | AccountStatusPage | Account state / onboarding status check |
| `/dashboard` | DashboardWorkspace | Main dashboard: stats, indices, ZeroLoss, quick orders |
| `/terminal` | TradingWorkspace | Full trading terminal: watchlist + live chart + order panel |
| `/market` | MarketPage | NSE market overview, stock screener |
| `/futures` | FuturesPage | Futures trading with F&O contracts |
| `/options` | OptionsPage | Live options chain with greeks |
| `/portfolio` | PortfolioPage | Holdings, P&L, transaction history |
| `/orders` | OrdersPage | Order book: pending, filled, cancelled |
| `/algo` | AlgoTradingPage | Algo strategy creation and management |
| `/zeroloss` or `/auto-alpha` | ZeroLossPage | ZeroLoss / Auto-Alpha strategy dashboard |
| `/mentor` | AIMentorPage | Grok AI trading mentor chat |
| `/leaderboard` | LeaderboardPage | Ranked user performance board |
| `/brokers` | BrokersPage | Broker connection management |
| `/select-broker` | BrokerSelectPage | Broker OAuth connection initiation |
| `/broker/callback` | BrokerCallbackPage | OAuth callback handler |
| `/settings` | SettingsPage | Profile, password, 2FA, theme |
| `/bug-report` | BugReportPage | User bug report submission |
| `/admin` | AdminAccessPage | Admin login gate |
| `/admin/panel` | AdminPanelPage | Full admin: users, runtime flags, announcements |
| `/admin/bug-reports` | AdminBugReportsPage | Admin bug report viewer |
| `/admin/root-control` | RootControlPage | Root-level system control |
| `/admin/audit-log` | AdminAuditLogPage | System audit log viewer |
| `/embed/chart` | ChartEmbed | Embeddable chart widget |

---

## 🛠️ Tech Stack (Summary)

### Backend (FastAPI + Python 3.11)
- **Framework**: FastAPI 0.109.2 with async SQLAlchemy + asyncpg
- **Database**: PostgreSQL 16 with Alembic migrations
- **Cache**: Redis 7 (AOF persistence, LRU eviction)
- **Auth**: JWT (HS256, access + refresh tokens) + TOTP 2FA + Firebase Auth
- **Broker Integration**: Zebu/MYNT WebSocket (wss://go.mynt.in/NorenWSTP/)
- **AI**: Grok API integration (AI Mentor)
- **Encryption**: AES-256-GCM for broker tokens

### Frontend (React 18 + Vite)
- **UI**: React 18 with Tailwind CSS 3.4.1
- **State**: Zustand (14 stores across `stores/` and `store/`)
- **Routing**: React Router DOM 6.22.1
- **Charts**: ZebuLiveChart (candlestick)
- **Notifications**: react-hot-toast

### Infrastructure
- **VPS**: Contabo Ubuntu (CloudPanel + Nginx reverse proxy)
- **Containers**: Docker + Docker Compose (4 services)
- **CI/CD**: GitHub Actions → GHCR → auto-deploy on push to main
- **SSL**: CloudPanel-managed Let's Encrypt

---

## 🚀 Quick Start (Development)

```bash
# 1. Clone the repo
git clone https://github.com/netguy001/alphasync.git
cd alphasync

# 2. Setup backend environment
cd backend
cp .env.example .env   # Fill in your secrets

# 3. Start all services
docker compose up --build

# 4. Frontend dev server (separate terminal)
cd frontend
npm install
npm run dev
```

See [DEPLOY.md](./DEPLOY.md) for production deployment.  
See [ARCHITECTURE.md](./ARCHITECTURE.md) for full technical reference.

---

## 📚 Documentation

| File | Purpose |
|------|---------|
| [README.md](./README.md) | Project overview (this file) |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | Full technical architecture reference (24 sections) |
| [DEPLOY.md](./DEPLOY.md) | Contabo VPS production deployment guide |
| [data_pipeline_architecture_report.md](./data_pipeline_architecture_report.md) | Deep-dive: real-time data pipeline & caching |
