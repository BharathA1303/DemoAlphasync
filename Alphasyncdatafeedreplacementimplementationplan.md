# AlphaSync — Admin-Controlled Zebu Data Feed: Implementation Plan

**Scope:** Replace the current data feed architecture (NSE/BSE bhavcopy ingestion + synthetic in-process tick generator) with a single **admin-owned Zebu MYNT OAuth broker connection** that ingests real market data, stores it in bulk (Postgres + CSV), and serves every user a **time-delayed replay** of that real data — for charts, quotes, and the paper-trading engine. No user ever gets true real-time data, and no order from this platform ever reaches a real exchange (virtual/paper money only).

Repo analyzed: `github.com/BharathA1303/DemoAlphasync` (branch `main`). References below use real paths from that repo.

---

## 1. What the repo actually does today (baseline)

This matters because your screenshot describes the symptom ("downloading from NSE/BSE, not simulating") but the code tells a slightly more specific story — two data systems coexist and neither is what you want:

| Component | File(s) | What it actually does today |
|---|---|---|
| **EOD ingestion** | `backend/data_layer/ingestion/{nse_bhavcopy,bse_bhavcopy,nse_fo_bhavcopy,mcx_bhavcopy,index_bhavcopy}.py` | Downloads **end-of-day bhavcopy files** from NSE/BSE/MCX (not Zebu, not live) once a day via APScheduler (`backend/data_layer/main.py`, cron at 19:00). This is a nightly close-price-only fetch. |
| **Tick "simulation"** | `backend/market_data/replay/replay_engine.py` (`UltraTickReplayEngine`) | Generates **synthetic** ticks in-process using a regime/volatility model seeded from the prior EOD close. It is not derived from any real intraday feed — it is a random walk shaped to look plausible. This is the "not really simulating [real market behavior]" problem you're describing. |
| **Provider** | `backend/providers/replay_provider.py`, `backend/providers/factory.py` | `create_provider()` **always** returns a `ReplayProvider` regardless of `broker`/`creds` passed in — live broker connections are intentionally disabled at the factory level today. |
| **Session model** | `backend/services/data_feed_session.py` (`DataFeedSessionManager`) | Already single-admin, single-shared-session (`MASTER_SESSION_ID`) — **this part is structurally what you want and will be reused**, not replaced. Every user is mapped to one shared provider. |
| **Admin panel (existing)** | `backend/routes/admin.py` — `GET/POST /api/admin/settings/data-feed`, `GET/POST /api/admin/simulation/zebu-credentials`, `POST /api/admin/simulation/zebu-import`, `GET /api/admin/simulation/status` | Admin can toggle the simulator on/off and store Zebu **QuickAuth** credentials (uid/password/factor2 — a static DOB/PAN, not OTP), but *only* to run a one-off historical EOD backfill (`data_layer/ingestion/zebu_import.py`). There is no OAuth flow, and this Zebu login is never used for a live/continuous session. |
| **Zebu client** | `backend/data_layer/ingestion/zebu_client.py` | Confirms: synchronous REST client, used "ONLY to pull real historical EOD candles... never for order placement or a continuous live session" (per its own docstring). |
| **DB model** | `backend/models/data_feed_config.py` (`DataFeedConfig`) | Single-row config table already has `broker`, `broker_client_code`, encrypted password/factor2/vendor code fields — reusable, needs new OAuth-specific columns (see §5). |
| **Delay gate (unused by main app)** | `backend/data_layer/core/delay_gate.py` | A **day-granular** compliance delay (`DELAY_DAYS`, default 3) built for the *separate* standalone data-layer licensing product (`backend/data_layer/main.py`, its own FastAPI app mounted for a developer portal). This is a different delay concept than what you're asking for (minute-level intraday delay) and lives in a different service — call this out explicitly so it isn't confused with the new delay engine in §7. |

**Net conclusion:** the "single shared admin session" skeleton already exists (`DataFeedSessionManager`) and should be kept. What must change is (a) the **source of truth** — real Zebu OAuth live data instead of a random-walk generator seeded from once-daily bhavcopy files, (b) **bulk storage** of that real data, and (c) a genuine **time-delay replay** of real price paths instead of a synthetic one.

---

## 2. Target architecture — end to end

```
                         ┌─────────────────────────────────────────────┐
                         │   ADMIN PANEL → Data Feed Panel (new UI)     │
                         │  Connect Zebu (OAuth) · Set delay · Monitor  │
                         └───────────────────┬───────────────────────────┘
                                              │ (1) OAuth connect/callback
                                              ▼
                         ┌─────────────────────────────────────────────┐
                         │        ZebuOAuthBroker (single instance)     │
                         │  access_token + refresh_token (admin-owned)  │
                         └───────────────────┬───────────────────────────┘
                                              │ (2) WebSocket touchline/depth
                                              ▼
                         ┌─────────────────────────────────────────────┐
                         │      LiveIngestionWorker (single process)    │
                         │  parses ticks → tags real_timestamp          │
                         └──────┬───────────────────────────┬──────────┘
                                │                            │
                 (3a) bulk write                 (3b) append-only file writer
                                ▼                            ▼
                  ┌─────────────────────┐        ┌───────────────────────────┐
                  │ PostgreSQL           │        │ CSV bulk files (rotating)  │
                  │ raw_ticks (EQ, hot   │        │ contracts_YYYYMMDD.csv     │
                  │ partitioned table)   │        │ options_YYYYMMDD.csv       │
                  └─────────┬───────────┘        └───────────────────────────┘
                            │
                            │ (4) DelayEngine reads "as of now() - delay"
                            ▼
                  ┌──────────────────────────────┐
                  │   DelayedCandleBuilder         │
                  │  builds 1m/5m candles from      │
                  │  REAL delayed ticks (no RNG)     │
                  └──────────────┬─────────────────┘
                                 │
              (5) ONLY during market hours          (6) after hours / always
                                 ▼                                ▼
                  ┌─────────────────────┐            ┌──────────────────────┐
                  │  Redis (delayed      │            │  PostgreSQL fallback  │
                  │  cache, market hrs)  │            │  (delayed last-close, │
                  └─────────┬───────────┘            │  delayed candles)     │
                            │                                     │
                            └───────────────┬─────────────────────┘
                                             ▼
                         ┌─────────────────────────────────────────────┐
                         │  DelayedMarketDataService (replaces          │
                         │  ReplayProvider as the "system" provider)    │
                         └───────────────────┬───────────────────────────┘
                                              │ (7) WebSocket to browsers
                                              ▼
                                    All AlphaSync users
                              (see prices delayed by admin-set N)
```

Key architectural decisions and why:

1. **Single ingestion session, admin-owned.** Only the admin authenticates against Zebu. Users never touch broker credentials — this is unchanged from today's `DataFeedSessionManager` design and is correct; only its data source changes.
2. **Real ticks are the source of truth**, not a statistical model. `UltraTickReplayEngine`'s regime/volatility generator is retired for equities/F&O/commodities that Zebu covers, and kept only as an emergency fallback (§9) for symbols with no live feed (e.g., feed outage, symbol not subscribed).
3. **Delay is enforced at the read layer, not the write layer.** Ingestion always writes the true (real) timestamp as fast as it arrives. The `DelayEngine` is what withholds anything newer than `now() - delay_seconds` from any user-facing query, cache, or WebSocket broadcast. This means a single admin-configurable delay knob (e.g. 60s, 5 min, 15 min) instantly governs the whole platform without touching ingestion code — and it's easy to audit/prove no real-time leakage happened, because leakage would require querying past the gate, which is centralized in one function.
4. **Orders never leave AlphaSync.** This is unchanged — no new order-routing code is introduced. Only the *price feed* pipeline changes.

---

## 3. Zebu OAuth — exact flow to implement (source: zebumyntapi.web.app/OAuth/*)

This is materially different from the QuickAuth flow already coded in `zebu_client.py` — that one does `uid/pwd/factor2` REST login. OAuth is a browser-redirect flow the admin completes once (matching your screenshot: "asks user id and client id and secret code and shows redirect url... redirects to broker page... username, password and otp/totp... comeback to alphasync").

**Credentials needed (obtained from MYNT app → Profile → API Key screen, per docs):** `client_id`, `secret_key`, and a registered **Redirect URL** + whitelisted IP(s). These are entered once by the admin in the new Data Feed Panel — not per user.

### Step-by-step

| # | Step | Endpoint | Notes |
|---|------|----------|-------|
| 1 | Admin enters `client_id`, `secret_key`, redirect URL in Data Feed Panel | — | Stored encrypted (AES-256-GCM, reuse `services/crypto.py` — same pattern as existing `broker_password_enc`) |
| 2 | Backend generates the login URL and shows/redirects admin to it | `GET https://go.mynt.in/OAuthlogin/authorize/oauth?client_id=<CLIENT_ID>` | This is what the panel's "Connect Broker" button opens (matches your screenshot flow) |
| 3 | Admin logs into MYNT in that window (username, password, OTP/TOTP as MYNT requires) | (Zebu-hosted) | Outside our control — Zebu's own login UI |
| 4 | Zebu redirects back to our **registered** redirect URL with `?code=<AUTH_CODE>` | `https://<our-domain>/api/admin/broker/zebu/oauth-callback?code=...` | Must exactly match what was registered in MYNT's API Key screen |
| 5 | Backend exchanges code for tokens | `POST https://go.mynt.in/NorenWClientAPI/GenAcsTok` | Body: `jData={"code": "<code>", "checksum": "<sha256>"}` where `checksum = sha256(client_id + secret_key + code)` |
| 6 | Store `access_token`, `refresh_token`, `expires_in` | — | Encrypted at rest, same as broker_accounts pattern in `services/crypto.py` |
| 7 | Use `access_token` as `Authorization: Bearer <token>` for REST calls (quotes, masters) | e.g. `POST https://go.mynt.in/NorenWClientAPI/GetQuotes` | |
| 8 | For WebSocket, do a `t: "c"` connect handshake with `uid`, `actid`, `source`, `susertoken` | `wss://go.mynt.in/NorenWSTP/` (same WS host already referenced in `ARCHITECTURE.md`) | `susertoken` here is the OAuth access token; confirm exact field name against a live response, older Noren WS docs call it `susertoken` — differs from `access_token` field name in REST, keep an explicit mapping constant |
| 9 | Refresh before expiry | `POST https://go.mynt.in/NorenWClientAPI/RefreshToken` with `{"refresh_token": "..."}` | `expires_in` is ~3600s per docs; schedule refresh at ~80% of TTL (~48 min) with retry/backoff |

### New backend module: `backend/providers/zebu_oauth_client.py`

Responsibilities (separate from the existing QuickAuth `data_layer/ingestion/zebu_client.py`, which stays as-is for the one-off historical import path — do not conflate the two):
- `build_authorize_url(client_id) -> str`
- `exchange_code_for_token(client_id, secret_key, code) -> {access_token, refresh_token, expires_in}`
- `refresh_access_token(refresh_token) -> {access_token, expires_in}`
- `get_quotes(exch, token) -> dict` (REST, Bearer auth)
- Async WebSocket client class `ZebuLiveFeed` — connect, `t:"c"` handshake, `t:"t"` touchline subscribe (`k: "NSE|22#BSE|508123#NFO|<token>"` batched, per docs' `#`-delimited scrip list), `t:"d"` depth subscribe if order-book depth is wanted later, reconnect with exponential backoff (mirror the existing `ZebuProvider` backoff constants noted in `ARCHITECTURE.md` §6: 1s base, 2x factor, 60s max, 50 attempts — same values, new class).

### DB schema addition — extend `DataFeedConfig` (`backend/models/data_feed_config.py`)

New columns (Alembic migration under `backend/alembic/versions/`):

```python
oauth_client_id = Column(String(100), nullable=True)
oauth_secret_key_enc = Column(Text, nullable=True)       # AES-256-GCM
oauth_redirect_url = Column(String(500), nullable=True)
oauth_access_token_enc = Column(Text, nullable=True)      # AES-256-GCM
oauth_refresh_token_enc = Column(Text, nullable=True)     # AES-256-GCM
oauth_token_expires_at = Column(DateTime(timezone=True), nullable=True)
oauth_connection_status = Column(String(50), default="disconnected")  # disconnected|awaiting_callback|connected|error
oauth_last_error = Column(Text, nullable=True)
feed_delay_seconds = Column(Integer, nullable=False, server_default=text("300"))  # admin-configurable delay
redis_active_market_hours_only = Column(Boolean, nullable=False, server_default=text("true"))
```

Follow the existing getter/setter pattern (`get_broker_password`/`set_broker_password`) for the new encrypted fields, reusing `services/crypto.py`.

---

## 4. Admin Panel — Data Feed Panel (UI/UX spec)

New/rebuilt frontend page, e.g. `frontend/src/pages/admin/DataFeedPanel.jsx` (adjacent to wherever the existing simulation toggle UI lives today, driven by `GET/POST /api/admin/settings/data-feed`).

**Panel sections:**

1. **Broker Connection**
   - Fields: Client ID, Secret Key (masked), Redirect URL (prefilled/read-only, shown so admin can copy it into the MYNT API Key screen), Primary/Secondary IP (informational — must match what's registered on Zebu's side)
   - Button: **"Connect via Zebu OAuth"** → opens `GET https://go.mynt.in/OAuthlogin/authorize/oauth?client_id=...` in a new tab/popup
   - Status badge: `Disconnected / Awaiting Callback / Connected / Error` (from `oauth_connection_status`)
   - "Disconnect" button → revokes locally stored tokens, stops `LiveIngestionWorker`

2. **Delay Configuration**
   - Numeric input: delay in seconds/minutes (`feed_delay_seconds`), with presets (60s, 5min, 15min) — this is the single knob mentioned in §2.3
   - Live preview: "Users currently see prices as of `<computed timestamp>`"

3. **Redis / Market Hours Toggle**
   - Checkbox: "Only cache in Redis during market hours" (`redis_active_market_hours_only`) — see §8

4. **Ingestion Monitor** (read-only, polling `GET /api/admin/data-feed/status`)
   - Ticks ingested today (count), last tick timestamp per exchange, WS connection uptime, symbols subscribed, DB write lag, CSV file sizes/row counts for today
   - Error log tail (last N ingestion errors)

5. **Symbol Universe**
   - Which exchanges are active (NSE/BSE/NFO/BFO/MCX toggles)
   - "Re-sync symbol master" button (see §6) with last-synced timestamp

6. **Bulk Storage**
   - Today's CSV files listed with download links (admin-only, signed URL or auth-gated static route)
   - Retention setting (days to keep raw ticks in Postgres before archiving/rolling up — see §7.4)

### New admin API routes (add to `backend/routes/admin.py`, alongside existing `/settings/data-feed` and `/simulation/*`)

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/admin/broker/zebu/oauth/configure` | Save client_id/secret_key/redirect_url |
| GET | `/api/admin/broker/zebu/oauth/authorize-url` | Return the constructed Zebu login URL |
| GET | `/api/admin/broker/zebu/oauth-callback` | Public-ish callback endpoint Zebu redirects to (validate `state`, exchange code, store tokens, start `LiveIngestionWorker`) |
| POST | `/api/admin/broker/zebu/oauth/disconnect` | Revoke/clear tokens, stop ingestion |
| GET | `/api/admin/data-feed/status` | Ingestion monitor payload (§4.4) |
| PUT | `/api/admin/data-feed/delay` | Update `feed_delay_seconds` |
| PUT | `/api/admin/data-feed/redis-policy` | Update `redis_active_market_hours_only` |
| POST | `/api/admin/data-feed/symbols/resync` | Re-download + reparse symbol masters (§6) |
| GET | `/api/admin/data-feed/bulk-files` | List today's/recent CSV bulk files with row counts |

Keep the existing `/api/admin/simulation/*` routes for the historical-EOD-backfill path (unaffected — still useful for pre-seeding new symbols/backtests) but relabel their frontend section as "Historical Backfill (Legacy)" so admins don't confuse it with live OAuth ingestion.

---

## 5. Symbol Mapping — Zebu Master Files (confirmed against uploaded files + docs)

Verified directly against your five uploaded files and `zebumyntapi.web.app/OAuth/Masters/`. All are downloaded from `https://go.mynt.in/<EXCHANGE>_symbols.txt.zip` (Bearer-auth'd under OAuth; the existing `zebu_client.download_symbol_master()` already targets this exact pattern, just needs the Bearer token instead of the legacy `Authorization: <susertoken>` header). Files update daily after market hours — re-sync should run once daily (post 19:00 IST, after the existing nightly ingestion cron) plus be triggerable on demand from the panel.

### Confirmed column layouts (from actual file headers)

| Exchange | File | Columns |
|---|---|---|
| **NSE** | `NSE_symbols.txt` (9,667 rows) | `Exchange, Token, LotSize, Symbol, TradingSymbol, Instrument, TickSize` — `Instrument` values seen: `EQ`, `BE`, `SM` (SME), `ST`, `INDEX` |
| **BSE** | `BSE_symbols.txt` (12,650 rows) | `Exchange, Token, LotSize, Symbol, TradingSymbol, Instrument, TickSize` — mostly `Instrument = F` (many are structured/fixed-income-looking BSE F instruments, not just cash equity — filter carefully, see §5.2) |
| **NFO** | `NFO_symbols.txt` (73,110 rows) | `Exchange, Token, LotSize, Symbol, TradingSymbol, Expiry, Instrument, OptionType, StrikePrice, TickSize` — `Instrument`: `OPTSTK`/`OPTIDX`/`FUTSTK`/`FUTIDX`; `OptionType`: `CE`/`PE`/`XX` |
| **BFO** | `BFO_symbols.txt` (37,263 rows) | Same shape as NFO |
| **MCX** | `MCX_symbols.txt` (15,654 rows) | `Exchange, Token, LotSize, GNGD, Symbol, TradingSymbol, Expiry, Instrument, OptionType, StrikePrice, TickSize` — extra `GNGD` column (good-till-date/tick-value multiplier factor); `Instrument`: `FUTCOM`, `OPTIDX`/`OPTFUT` |

This matches the docs' stated field set (Symbol, Token, Exchange, Segment, Instrument Type, Lot Size, Tick Size, Expiry, Strike) — the real files are CSV (comma-delimited, trailing comma per row) rather than the `|`-delimited example in the docs' Python snippet; **parse by comma, ignore the docs' pipe-split example.**

### 5.1 New ingestion module: `backend/data_layer/ingestion/zebu_symbol_master.py`

- Downloads all 5 zip files via the OAuth Bearer client
- Parses each into a normalized `SymbolMaster` row: `{exchange, token, trading_symbol, display_symbol, instrument_type, lot_size, tick_size, expiry, strike, option_type}`
- Upserts into a new table `symbol_master` (see §5.3), keyed on `(exchange, token)`, versioned by `synced_at` so stale symbols (delisted, expired contracts) can be detected (present in old sync, absent in new one) and flagged `is_active=false` rather than deleted (preserves FK integrity for historical ticks/CSV references)

### 5.2 Filtering rules (important, prevents junk symbols entering the live subscription set)

- **NSE**: subscribe only `Instrument IN ('EQ','INDEX')` for the default universe; `BE`/`SM`/`ST` opt-in per admin (BE = trade-for-trade, SM/ST = SME/InvIT, thin liquidity)
- **BSE**: the sample shows large volumes of `Instrument = 'F'` rows with numeric-prefixed symbols (e.g. `1190PFL28`) — these are BSE fixed income/structured instruments, **not equities**. Cross-reference `TradingSymbol` pattern and `LotSize` (equities are typically `LotSize=1`) before treating a BSE row as a tradable cash-equity mapping; default the platform's "BSE stocks" watchlist to a curated allow-list rather than the raw file
- **NFO/BFO**: default subscription = current + next-month `FUTIDX`/`FUTSTK` for symbols already in `backend/providers/contract_symbol_map.py`'s existing pre-mapped set (RELIANCE, TCS, NIFTY, BANKNIFTY, etc.), plus near-the-money `OPTIDX` strikes (e.g. ±10 strikes around spot) — subscribing all 73K+37K NFO/BFO rows to the live WS is neither necessary nor advisable (see §9 on subscription budget)
- **MCX**: default to the commodities already listed in `ARCHITECTURE.md` §7 ("GOLD, SILVER, CRUDEOIL, etc.") — expand via admin panel, same near-month logic as F&O

### 5.3 New table `symbol_master`

```sql
CREATE TABLE symbol_master (
    exchange        VARCHAR(10) NOT NULL,
    token           VARCHAR(20) NOT NULL,
    symbol          VARCHAR(50) NOT NULL,       -- underlying, e.g. "RELIANCE"
    trading_symbol  VARCHAR(100) NOT NULL,      -- e.g. "RELIANCE-EQ", "NIFTY26SEP26C25000"
    instrument_type VARCHAR(20) NOT NULL,       -- EQ, INDEX, FUTSTK, OPTIDX, FUTCOM, ...
    lot_size        INTEGER NOT NULL DEFAULT 1,
    tick_size       NUMERIC(10,4) NOT NULL DEFAULT 0.05,
    expiry          DATE NULL,
    strike          NUMERIC(12,2) NULL,
    option_type     VARCHAR(2) NULL,            -- CE, PE
    is_active       BOOLEAN NOT NULL DEFAULT true,
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (exchange, token)
);
CREATE INDEX ix_symbol_master_symbol ON symbol_master (symbol, exchange);
CREATE INDEX ix_symbol_master_active ON symbol_master (is_active) WHERE is_active;
```

This becomes the single source of truth for exchange↔token↔trading_symbol mapping, replacing/feeding the existing `backend/providers/contract_symbol_map.py` static maps (keep that file as a curated "priority subscription list" that references `symbol_master`, rather than duplicating raw data).

---

## 6. Live Ingestion Worker

New module: `backend/workers/live_feed_ingestion_worker.py` (sits alongside existing workers listed in `ARCHITECTURE.md` §8, started/stopped from the same lifespan hooks as `market_worker.py` today).

### Responsibilities
1. On admin "Connect" (OAuth complete) or on process startup if already connected: open one `ZebuLiveFeed` WebSocket session, subscribe to the active `symbol_master` universe (§5.2 filters) in batches (Zebu's touchline `k` field supports `#`-delimited multi-scrip subscribe in one request — batch ~200 symbols per subscribe call to avoid oversized frames)
2. On every `tf`/`df` tick message: normalize fields (`lp`→last_price, `v`→volume, `o/h/l/c`, `ft`→feed_time) — same normalization concept already used in `ZebuProvider._handle_tick` per `ARCHITECTURE.md` §6, reuse that mapping table
3. Write-through to **two** sinks per tick (§7):
   - Postgres `raw_ticks` (equity + index; hot path, queryable)
   - CSV bulk writer for **contracts (futures) and options** specifically, per your requirement ("equity and contracts and options saves in a csv file")
4. Never write directly to Redis or broadcast directly to user WebSockets from here — that is the `DelayEngine`'s job (§7.5), keeping ingestion and delayed-serving fully decoupled so a bug in one can't leak real-time data through the other

### Reconnection & health
- Reuse the backoff constants noted in the current `ZebuProvider` (1s→60s exponential, 50 attempts)
- On `access_token` expiry (WS disconnect with auth error, or REST 401), trigger `refresh_access_token()`; on refresh failure, flip `oauth_connection_status = "error"`, alert admin panel, and — per your "no live data ever shown as if not delayed" requirement — freeze the delayed feed at its last known state (serve last available delayed data, clearly flagged `feed_stale: true`) rather than silently falling back to synthetic data without telling anyone

---

## 7. Bulk Storage Strategy

### 7.1 Equity + Index → PostgreSQL (`raw_ticks`)

```sql
CREATE TABLE raw_ticks (
    id              BIGSERIAL,
    exchange        VARCHAR(10) NOT NULL,
    token           VARCHAR(20) NOT NULL,
    symbol          VARCHAR(50) NOT NULL,
    ltp             NUMERIC(12,4) NOT NULL,
    open            NUMERIC(12,4),
    high            NUMERIC(12,4),
    low             NUMERIC(12,4),
    close           NUMERIC(12,4),
    volume          BIGINT,
    best_bid        NUMERIC(12,4),
    best_ask        NUMERIC(12,4),
    real_timestamp  TIMESTAMPTZ NOT NULL,   -- true broker feed time (ft), never shown to users directly
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (id, real_timestamp)
) PARTITION BY RANGE (real_timestamp);
```

- **Daily partitions** (`raw_ticks_2026_07_31`, etc.), created a day ahead by a small scheduled job — this is what makes "huge bulk" data manageable; querying/pruning one day's partition is O(that day), not O(everything)
- Index: `(exchange, token, real_timestamp DESC)` per partition, for fast "give me delayed ticks since X" reads
- **Batch inserts**: buffer ticks in-memory for ~250ms or 200 rows (whichever first) and `COPY`/`executemany` in bulk — never one `INSERT` per tick; this is the single biggest lever against "DB will fire out due to huge number [of] data" (your words) under full-market-hours load (thousands of symbols × multiple ticks/sec)
- **Retention**: raw tick-level rows older than N days (admin-configurable, default 7) get rolled up into 1-minute OHLCV candles in a separate smaller `candles_1m` table and the raw partition is dropped — keeps disk bounded while candle history stays forever

### 7.2 Contracts (Futures) + Options → CSV bulk files

Per your explicit requirement, F&O writes go to CSV rather than the hot Postgres table (these are much higher cardinality — 73K+37K instruments across NFO/BFO alone — and don't need row-level SQL queryability the way equity ticks do; delayed candle building for F&O reads from the CSVs in batch).

- Path convention: `data/bulk/{contracts|options}/{exchange}/{YYYY-MM-DD}/{exchange}_{segment}_{HHmm}.csv` — new file every rotation window (default: every 15 minutes, or every N MB, admin-configurable) to keep individual files small and appendable
- Columns: `real_timestamp, exchange, token, trading_symbol, instrument_type, expiry, strike, option_type, ltp, open, high, low, close, volume, oi, best_bid, best_ask`
- Writer uses buffered append (`csv.writer` over a kept-open file handle, `flush()` every batch, not every row) — same batching discipline as §7.1
- A lightweight **CSV index table** in Postgres (`bulk_file_index: file_path, exchange, segment, date, row_count, start_ts, end_ts`) lets the DelayEngine/admin panel find "which file has minute X" without scanning the filesystem
- **Compression + archival**: rotate previous day's CSVs through gzip after market close (cron, same nightly window as bhavcopy ingestion) — keeps live-day files fast to append while older ones shrink ~10x on disk

### 7.3 Why this split (equity→DB, F&O→CSV) rather than one system for everything
- Matches your explicit instruction directly
- Equity/index needs random-access point queries (single stock quote, chart range) → relational index is the right tool
- F&O bulk (options chains especially) is naturally append-mostly, read-in-bulk-by-time-window (build a whole chain snapshot at once) → sequential file read is cheap and doesn't bloat the primary OLTP database with 100K+ instrument-rows-per-tick-cycle

### 7.4 Guardrails against "DB fired out" (your term for DB overload)
- Batched writes (§7.1) — never per-tick commits
- Partitioning by day — bounds index size, makes retention a `DROP TABLE`, not a slow `DELETE`
- Connection pool sizing: keep existing `DB_POOL_SIZE=20 / DB_MAX_OVERFLOW=10` (per `ARCHITECTURE.md` §23) but route ingestion writes through a **dedicated** small pool (2-4 connections) separate from the user-facing API's pool, so a burst of ticks can never starve user requests
- Backpressure: if the ingestion write buffer exceeds a high-water mark (e.g. 5,000 buffered rows) because Postgres is slow, start dropping the lowest-priority symbols' ticks (mirrors the existing `SymbolPriorityEngine` HOT/WARM/COLD concept from `ARCHITECTURE.md` §7 — reuse it here for ingestion admission control, not just outbound throttling)

---

## 8. Redis — Market-Hours-Only Policy

Today Redis (per `ARCHITECTURE.md` §15 / `data_pipeline_architecture_report.md` §4) caches quotes with a 120s TTL during active hours and a much longer TTL (24h) when closed, and is always running. You want the opposite emphasis: **Redis should only be an active hot-cache during live market hours**; outside market hours, serve from Postgres directly (data isn't changing anyway, so the cache buys nothing but memory).

### Implementation
- Reuse the existing NSE session-state machine already defined in `backend/engines/market_session.py` (`ARCHITECTURE.md` §11: PRE_MARKET/OPEN/CLOSING/AFTER_MARKET/CLOSED) as the single source of truth for "are we in market hours" — do not build a second clock
- `DelayEngine` (§7.5 below) checks `market_session.is_open_ish()` (open, pre-market, closing) before touching Redis:
  - **Market hours**: write delayed quotes/candles to Redis with short TTL (mirror existing 120s), read-through cache in front of Postgres
  - **Outside market hours**: skip Redis entirely — read the last delayed snapshot directly from `candles_1m`/`raw_ticks` (or the CSV index for F&O) with a normal DB query; also **actively flush/expire** the market-hours keys at the `OPEN→CLOSING` transition (a scheduled task, not just relying on TTL) via `FLUSHDB`-scoped-by-prefix on the `alphasync:price:*` / `alphasync:history:*` keyspace (per `data_pipeline_architecture_report.md` §4's existing key schema) so idle memory doesn't sit around all night
- Config flag `redis_active_market_hours_only` (added in §3's `DataFeedConfig` migration) lets the admin panel toggle this off (fall back to current always-on Redis behavior) if there's ever a reason to, without a code change

---

## 9. Delay Engine + Delayed Candle Construction

This is the module that actually satisfies "I don't want market real time data, want some delay while changing in the price data."

### 9.1 `backend/services/delay_engine.py` (new)

```python
def get_visible_cutoff(feed_delay_seconds: int) -> datetime:
    """Anything with real_timestamp > this is invisible to users."""
    return now_utc() - timedelta(seconds=feed_delay_seconds)

async def get_delayed_quote(symbol, exchange) -> QuoteDTO:
    cutoff = get_visible_cutoff(current_delay_setting())
    # market hours: Redis-first (see §8), else DB
    row = await fetch_latest_tick_at_or_before(symbol, exchange, cutoff)
    return to_quote_dto(row, as_of=cutoff)
```

This single gate function is called by **every** read path — REST quote endpoints, WebSocket broadcast loop, candle builder, options chain builder — so there is exactly one place in the codebase that decides what "now" means for a user, matching your explicit requirement that nothing show real-time data. This deliberately replaces `ReplayProvider`/`InternalSimProvider`/`UltraTickReplayEngine` as the thing users' WebSocket subscriptions are fed from — those synthetic generators are retired for symbols with a real Zebu feed (kept only as the fallback in §9.3).

### 9.2 Delayed candle builder — "must match the stock data and candle LTP changing"

New module: `backend/market_data/replay/delayed_candle_builder.py`, replacing the tick-aggregation half of `backend/workers/market_worker.py`'s current job (which currently aggregates the *synthetic* replay ticks per `data_pipeline_architecture_report.md` §1.B).

- Runs on the same cadence as today's `MarketDataWorker` (3s during market hours per `ARCHITECTURE.md` §8) but instead of aggregating live in-memory ticks from a generator, it:
  1. Computes `cutoff = get_visible_cutoff(delay)`
  2. Pulls `raw_ticks` (or CSV rows for F&O, via the `bulk_file_index`) between `[last_candle_close_time, cutoff]`
  3. Builds true OHLC from those **real** rows (open = first tick's ltp in window, high/low = real max/min, close = last tick's ltp, volume = sum) — because this is real historical data being replayed on a lag, the candle shapes and the LTP path are, by construction, identical to what actually happened on the exchange — just shifted later in time. This directly satisfies "candle movement which must be matching with the stock data and candle ltp changing."
  4. Writes the finished candle to `candles_1m`/`candles_5m` and (market hours only, per §8) Redis
- Because the source is real, no Brownian-bridge/regime model is needed for any symbol with live Zebu coverage — `simulator/brownian_bridge.py` and `market_data/replay/replay_engine.py`'s dynamic generator are **retired from the main serving path** (kept as vendored code, not deleted, for the fallback case below and for the still-useful EOD-only historical backfill in the standalone data-layer product)

### 9.3 Fallback (explicit, not silent)

If a symbol has no live tick within a reasonable staleness window (e.g. Zebu doesn't cover it, WS dropped, market holiday), the DelayEngine returns the **last real delayed price flat** rather than inventing movement — this is more honest than synthetic noise and is what "delay while changing in the price data" implies: delay real change, don't manufacture fake change. Only pre-open weekend/holiday demo scenarios (if ever needed for always-on-24/7 demo/practice per `SIMULATION_MODE`) should fall back to the existing Brownian-bridge engine, and the API response should mark such candles `source: "synthetic_fallback"` so the frontend can (optionally) show a small "demo data" indicator — full transparency, no ambiguity about what users are looking at.

---

## 10. Provider/Session Layer Changes (what actually gets swapped)

| Today | Becomes |
|---|---|
| `providers/factory.py::create_provider()` always returns `ReplayProvider` | Returns a new `DelayedFeedProvider` (thin adapter implementing the same `MarketProvider` interface from `providers/base.py`, but backed by `DelayEngine` reads instead of `ReplayProvider`'s synthetic ticks) |
| `services/data_feed_session.py::DataFeedSessionManager` — master session wraps `InternalSimProvider` | Keep the manager, retarget: master session now wraps the new `DelayedFeedProvider`. `initialize_master_session()`/`reload_data_feed()` logic (enable/disable, status tracking) is reused nearly as-is — just swap which provider class gets instantiated |
| `services/market_data.py::get_quote/get_system_quote` | Unchanged call sites; internally now route to `DelayEngine.get_delayed_quote()` — this means **no changes needed** in `routes/market.py`, `routes/orders.py`, `routes/portfolio.py`, the trading engine, or the algo/ZeroLoss engines, since they all already go through `market_data.py`'s service layer, not the provider directly. This significantly limits blast radius. |
| `backend/workers/market_worker.py` | Split: keep its ticker/header-aggregation responsibilities (`_build_ticker_items`, Redis publish of `alphasync:ticker:all` etc. per `data_pipeline_architecture_report.md` §1.D), but delegate OHLC aggregation to the new `delayed_candle_builder.py` (§9.2) |
| `backend/market/quote_coordinator.py`, `symbol_priority_engine.py` | Reused as-is for throttling **within** the delayed broadcast to browsers (HOT/WARM/COLD tiers, per `ARCHITECTURE.md` §7 — this UX-facing throttling is orthogonal to the delay-gate change and stays useful) |

**Not changed:** JWT auth, order placement/fill logic, risk engine, portfolio math, ZeroLoss strategy internals, WebSocket connection management to the frontend, frontend Zustand stores. This plan is scoped tightly to the market-data sourcing and delay layer, exactly as requested ("replace the entire data feed architecture" — meaning the feed, not the trading engine around it).

---

## 11. Migration / Rollout Phases

**Phase 0 — Non-breaking groundwork** (safe to ship immediately, no behavior change)
- Alembic migration: `symbol_master`, `raw_ticks` (partitioned), `bulk_file_index`, new `DataFeedConfig` columns
- `zebu_oauth_client.py` module (unused until Phase 2)
- `zebu_symbol_master.py` sync job — run once, populate `symbol_master`, verify row counts against your 5 uploaded files as a sanity check (9,667 / 12,650 / 73,110 / 37,263 / 15,654)

**Phase 1 — Admin panel plumbing (feature-flagged off)**
- New admin routes (§4) + Data Feed Panel UI, gated behind a `broker_live_feed_enabled` flag that defaults `false` so today's simulator keeps serving users unaffected
- Admin completes OAuth connect in a staging/test environment first; verify token exchange + WS handshake against Zebu's sandbox (`uat.mynt.in`, per docs' Base URL table) before touching production credentials

**Phase 2 — Shadow ingestion** (still not user-facing)
- `LiveIngestionWorker` runs and writes to `raw_ticks`/CSV, but `DelayEngine` is not yet wired into `market_data.py` — this validates ingestion throughput, DB write latency, and CSV rotation under real market load with zero user risk
- Watch the Ingestion Monitor (§4.4) for a full trading day; confirm partition sizes, batch-write latency, and reconnect behavior around the 09:15 open (highest tick-rate period)

**Phase 3 — Cutover**
- Flip `providers/factory.py` to return `DelayedFeedProvider` (behind the same admin flag, so it's an instant rollback: flag off = back to `ReplayProvider` immediately)
- Start with delay = 15 minutes (a conservative, clearly-non-real-time value) and a small symbol universe (top 50 NSE stocks + Nifty/BankNifty), then widen coverage over subsequent days
- Keep `UltraTickReplayEngine`/`InternalSimProvider` code paths intact (not deleted) as the documented fallback (§9.3) and instant-rollback target

**Phase 4 — Full cutover + cleanup**
- Expand symbol universe to full F&O/MCX coverage per §5.2 filters
- Reduce delay to your target operating value
- After a stable burn-in period, remove the feature flag (keep the code, just default it permanently on) and update `ARCHITECTURE.md`/`data_pipeline_architecture_report.md` to describe the new pipeline (both docs currently describe the old zero-delay design and will otherwise mislead the next person who reads them)

---

## 12. Configuration Summary (new environment variables / settings)

| Variable | Default | Purpose |
|---|---|---|
| `ZEBU_OAUTH_CLIENT_ID` | — | Set via admin panel (DB-stored), not required as an env var, but supportable as an initial-seed override |
| `ZEBU_OAUTH_BASE_URL` | `https://go.mynt.in` | Sandbox override: `https://uat.mynt.in` |
| `FEED_DELAY_SECONDS_DEFAULT` | `900` (15 min) | Initial value for `DataFeedConfig.feed_delay_seconds` before admin changes it |
| `RAW_TICKS_RETENTION_DAYS` | `7` | Partition drop threshold (§7.1) |
| `BULK_CSV_ROTATE_MINUTES` | `15` | CSV file rotation window (§7.2) |
| `BULK_CSV_DIR` | `/data/bulk` | Mounted volume for CSV output — add a new named Docker volume (alongside existing `pgdata`/`redisdata`/`uploads` in `docker-compose.yml`) so bulk files survive container restarts |
| `INGESTION_DB_POOL_SIZE` | `4` | Dedicated small pool for the ingestion worker (§7.4) |
| `SYMBOL_MASTER_SYNC_HOUR` | `19` (matches existing nightly cron) | Daily re-sync time |

---

## 13. Testing Checklist

- [ ] OAuth: authorize → callback → token exchange → WS connect, against Zebu sandbox first
- [ ] Token refresh fires correctly before `expires_in` elapses; WS reconnects using refreshed token without dropping the ingestion worker
- [ ] Symbol master sync row counts match expected magnitudes per exchange (§5); verify `is_active` correctly flips for delisted/expired instruments on second sync
- [ ] Load test ingestion at full NSE cash-market open volume; confirm batch-write latency stays bounded and no `raw_ticks` write backlog forms
- [ ] Confirm `DelayEngine.get_visible_cutoff()` is the *only* code path returning tick data to any user-facing route — grep for any remaining direct `ReplayProvider`/`InternalSimProvider` reads that bypass it
- [ ] Confirm candle OHLC built from delayed real ticks reproduces the real exchange candle shape exactly, just time-shifted (spot-check a few symbols against a public delayed-quote source)
- [ ] Confirm Redis keys are absent/flushed outside market hours and quotes still resolve correctly from Postgres in that window
- [ ] Confirm CSV files rotate on schedule, `bulk_file_index` stays in sync, and gzip archival runs post-close without blocking live writes
- [ ] Kill the WS mid-session; confirm reconnect/backoff, and confirm the frontend never displays data marked stale as if it were live
- [ ] Full end-to-end: admin sets delay to 60s in a test window, confirms via the panel's "as of" timestamp that displayed prices are consistently ~60s behind a reference live source

---

## 14. Summary of what changes vs. what doesn't

**Changes:**
- Data source: NSE/BSE bhavcopy + synthetic generator → real Zebu OAuth live feed (admin-owned)
- Storage: adds `raw_ticks` (partitioned, bulk) + rotating CSV bulk files for F&O
- Serving: adds a centralized `DelayEngine` gate; candles are built from real delayed ticks, not a regime model
- Redis: scoped to market hours only, actively flushed at close
- Admin panel: new Data Feed Panel (OAuth connect, delay control, ingestion monitor, symbol universe, bulk file access)

**Does not change:**
- Per-user experience of placing paper trades, portfolio math, risk engine, ZeroLoss strategy, algo engine
- Authentication/JWT, frontend component structure, WebSocket transport mechanics to browsers
- The fact that this remains a 100% virtual/paper-trading platform — no order ever reaches a real exchange, regardless of feed source