# Alice Blue Broker Integration & Architecture

This document provides a detailed technical explanation of the Alice Blue broker integration within the AlphaSync platform. It covers the end-to-end lifecycle—from initial connection and authentication, real-time WebSocket tick ingestion, data caching layers, PostgreSQL schemas, and historical data retrieval, to simulated order placement and the system safety guards.

---

## 1. Protocol & Integration Overview

AlphaSync integrates with the Alice Blue **ANT OpenAPI** v2.0 protocol. The architecture uses:
*   **REST API Channel**: Used for WebSocket session initialization (`createWsSess`), on-demand quote queries (`getScripQuoteDetails`), historical chart fetches, and contract master CDNs.
*   **WebSocket Channel**: A persistent connection to Alice Blue’s NorenWS server, which handles real-time market data streaming.

### Base Connection Endpoints
*   **WebSocket URL**: `wss://ws1.aliceblueonline.com/NorenWS` (Configured via `ALICE_BLUE_WS_URL`)
*   **REST API Base**: `https://a3.aliceblueonline.com/open-api` (Configured via `ALICE_BLUE_API_URL`)

---

## 2. Authentication Flows & Session Lifecycle

AlphaSync provides both OAuth redirection logins and automated headless authentication for Alice Blue.

```
       [Standard OAuth Flow]                          [Headless QuickAuth Flow]
                 │                                               │
 1. GET /api/broker/aliceblue/connect                    1. POST /api/broker/aliceblue/login
                 │                                               │
 2. Redirect User to ANT Login                           2. Retrieve Saved App Credentials
                 │                                         (App Code + Password + TOTP Secret)
 3. User Login & Success Redirect                                │
                 │                                       3. Calculate Checksum & Validate
 4. GET /api/broker/callback/aliceblue?code=...             checksum = sha256(uid+totp+secret)
                 │                                               │
 5. Request User Session Token via                       4. POST /customer/webLoginValidateOTP
    /vendor/getUserDetails                                       │
                 │                                               │
                 └──────────────┬────────────────────────────────┘
                                │
                     [Success: Get userSession]
                                │
                  5. Encrypt (AES-256-GCM) & Store
                     in PostgreSQL (broker_accounts)
```

### A. Web OAuth / AppCode Authentication
1.  **Authorization Redirect**: The user visits `GET /api/broker/aliceblue/connect`. The server builds a redirect link using the user's registered App Code (`api_key`):
    ```
    https://a3.aliceblueonline.com/open-api/od/v1/profile/authorize?appcode=<app_code>
    ```
2.  **Callback Exchange**: The broker redirects the browser back to `GET /api/broker/callback/aliceblue?code=<auth_code>&userId=<client_id>`.
3.  **Checksum Exchange**: To obtain a session token (`userSession`), the backend generates a SHA-256 checksum hash:
    $$\text{Checksum} = \text{SHA256}(\text{client\_id} + \text{auth\_code} + \text{api\_secret})$$
    A POST request is sent to `ALICE_BLUE_SESSION_URL`:
    ```
    POST https://ant.aliceblueonline.com/open-api/od/v1/vendor/getUserDetails
    Content-Type: application/json
    {"checkSum": "<checksum>"}
    ```
4.  **Session Token**: The API returns the `userSession` token, which is stored as the active session key.

### B. Headless Auto-Authentication
For background workers, AlphaSync supports headless login using saved App Code, API Secret, Trading Password, and a TOTP Base32 Key:
1.  **TOTP Validation**: The system uses `pyotp.TOTP` to generate the current 6-digit TOTP code.
2.  **Authentication Sequence**: The provider attempts three fallback strategies to get a session:
    *   **Strategy 1 (Checksum)**: Uses the current 6-digit TOTP code as the `auth_code` in the checksum exchange.
    *   **Strategy 2 (Password Checksum)**: Uses the SHA-256 hash of the password as the `auth_code` in the checksum exchange.
    *   **Strategy 3 (webLoginValidateOTP)**: Sends a direct POST to Alice Blue’s legacy validate endpoint:
        ```
        POST https://ant.aliceblueonline.com/rest/AliceBlueAPIService/api/customer/webLoginValidateOTP
        jData={"userId":"<uid>","enc":"sha256(sha256(pwd)+sha256(totp))","factor2":"<totp>","imei":"alphasync-...","source":"API"}
        ```

### C. Session Management & Decryption
*   **Encrypted Storage**: The active session token and credentials are encrypted using **AES-256-GCM** (via `broker_crypto.py`) and stored in the PostgreSQL table `broker_accounts`.
*   **Token Expiry**: Alice Blue session tokens expire daily (typically after 8 hours). The background health checks in `BrokerSessionManager` monitor the `token_expiry` column and invalidate expired sessions.

---

## 3. WebSocket Connection & Tick Ingestion

Before connecting to the WebSocket, Alice Blue requires session registration.

### A. Pre-Connection WS Session Init
Prior to connecting the WebSocket, the provider sends a POST request to create a WebSocket session on the server:
```
POST https://a3.aliceblueonline.com/open-api/od/v1/profile/createWsSess
Authorization: Bearer <session_token>
Content-Type: application/json
{"source":"API","userId":"<userId>"}
```

### B. Connection Handshake & Double SHA-256 Hash
Once connected to `wss://ws1.aliceblueonline.com/NorenWS`, the client must send an authentication payload.
*   **Double SHA-256**: The `susertoken` must be a double SHA-256 hash of the raw session token:
    $$\text{hashed\_token} = \text{SHA256}(\text{SHA256}(\text{session\_token}))$$
*   **UserId Suffix**: The `uid` and `actid` fields must be appended with the suffix `_API`:
    ```json
    {
      "t": "c",
      "uid": "<client_id>_API",
      "actid": "<client_id>_API",
      "susertoken": "<double_hashed_token>",
      "source": "API"
    }
    ```
Alice Blue acknowledges successful authentication with `{"t":"cf","k":"OK"}`.

### C. Heartbeat Loop
*   **Interval**: Heartbeat messages are sent once every 50 seconds.
*   **Payload**: The payload has the form `{"t": "h", "k": ""}`.
*   *Note: Alice Blue does not respond to heartbeats with pong messages or acknowledge low-level WebSocket ping frames. The heartbeat is sent only to keep the WebSocket connection active.*

### D. Reconnection Protocol
If the connection is severed, the system triggers `_reconnect()` using exponential backoff:
*   **Delay**: Capped at a maximum of 60 seconds.
*   **Attempts**: Retries up to 50 times.
*   **State Recovery**: Upon reconnection, the provider resubscribes to all active symbols recorded in `_subscribed_symbols`.

---

## 4. Symbol Mapping & Tick Normalization

Alice Blue uses the same standard NSE token IDs as Zebu, allowing them to share the contract master databases.

### A. Symbol Mapper CDN
When mapping new symbols, the Alice Blue provider downloads exchange-specific contract files from the Alice Blue CDN:
```
https://v2api.aliceblueonline.com/restpy/static/contract_master/V2/{EXCHANGE}
```
*   **Resolving derivative contracts**: The mapper extracts expiry and strike details, registers them in `_ZEBU_SYMBOL_MAP`, and links the token ID to the canonical symbol in the reverse map.

### B. Tick Parsing
Incoming WebSocket updates (types `tk` / `tf` or depth feeds `dk` / `df`) are parsed and normalized:

| Alice Blue Field | AlphaSync Key | Description |
| :--- | :--- | :--- |
| `tk` | `token` | Token ID |
| `e` | `exchange` | Exchange (NSE, BSE, NFO, MCX) |
| `ts` | `name` | Trading symbol |
| `lp` | `price` / `ltp` | Last traded price |
| `v` | `volume` | Cumulative trading volume (handled dynamically) |
| `o`, `h`, `l` | `open`, `high`, `low` | Session open, high, and low prices |
| `c` | `close` / `prev_close` | Previous day's close price |
| `pc` | `change_percent` | Percentage change |
| `cv` | `change` | Absolute change value |
| `bp1`, `sp1` | `bid_price`, `ask_price` | Best bid and ask prices |
| `bq1`, `sq1` | `bid_qty`, `ask_qty` | Best bid and ask quantities |
| `oi` | `oi` | Open Interest |
| `ap` | `avg_price` | Volume-weighted average price |

*To prevent values from being overwritten, update ticks are merged with the process-local cache (`_price_cache`).*

---

## 5. Dual-Layer Caching & Redis Architecture

To achieve sub-millisecond read times for the API and frontend connections, AlphaSync employs a two-tier caching strategy.

```
Incoming Websocket Ticks ──────► [L1: SmartCache] (Process-local, <1µs)
                                       │
                                       ▼
                              [L2: Redis Cache] (Shared, ~1-2ms)
                                       │
                ┌──────────────────────┴──────────────────────┐
                ▼                                             ▼
       [Hot Cache Keys]                              [Derived Batch Hashes]
  alphasync:price:{symbol} (TTL 120s)            alphasync:price:all (Hash Map)
  alphasync:price:{symbol}:ts                    alphasync:ticker:all (Ticker bar)
                                                 alphasync:indices:all (Indices)
                                                 alphasync:commodities:all (Commodities)
```

### A. L1 Cache: SmartCache
*   Implemented as a process-local `OrderedDict` with a size limit (LRU eviction).
*   Enables the backend to resolve the latest price in `< 1µs`, preventing thread starvation on high-frequency API requests.

### B. L2 Cache: Redis Key Design
The Redis schema under the `alphasync` namespace isolates duties and optimizes lookups:
*   **Real-time Quotes**:
    *   `alphasync:price:{symbol}` (String): JSON payload of the normalized quote.
    *   `alphasync:price:{symbol}:ts` (String): Epoch timestamp of the last write.
    *   *TTL Management*: Short TTL of **120 seconds** during market hours (`MarketState.OPEN`). When the market is closed or on holiday, the TTL is extended to **86,400 seconds (24 hours)** to retain the last available price.
*   **Batch Reads**:
    *   `alphasync:price:all` (Hash): Map of `symbol` → `JSON quote`. Allows the system to pull all quotes in a single network round-trip.
*   **Persistent Snapshots**:
    *   `alphasync:last_price:{symbol}` (String): Persistent quote snapshot with no TTL, used to populate pages during closed hours or holiday periods.
*   **Active Subscriptions**:
    *   `alphasync:subscriptions` (Set): List of symbols currently monitored by the WebSocket feeds.
*   **Aggregated Tickers**:
    *   `alphasync:ticker:all` (String): JSON list containing combined quote stats for dashboard UI widgets (TTL 10s).
    *   `alphasync:indices:all` / `alphasync:commodities:all` (String): Exclusively index/commodity statistics (TTL 10s).

---

## 6. End-to-End Market Data Pipeline

The path of a market quote from the broker to the client interface:

```
                  ┌──────────────────────┐
                  │ Alice Blue WebSocket │
                  └──────────┬───────────┘
                             │ (Tick: Exchange|Token + LP)
                             ▼
                  ┌──────────────────────┐
                  │  AliceBlueProvider   │
                  └──────────┬───────────┘
                             │ (zebu_token_to_canonical lookup)
                             ▼
                  ┌──────────────────────┐
                  │   QuoteCoordinator   │
                  └──────────┬───────────┘
                             ├─────────────────────────────────────────┐
                             │ (Changed? Yes)                          │ (Changed? No)
                             ▼                                         ▼
                 ┌───────────────────────┐                  ┌──────────────────────┐
                 │ Write to SmartCache   │                  │  Write to SmartCache │
                 │ Write to Redis Cache  │                  └──────────────────────┘
                 │ Publish EventBus Event│
                 └──────────┬────────────┘
                            │ (PRICE_UPDATED)
                            ▼
                 ┌───────────────────────┐
                 │   WebsocketManager    │
                 └──────────┬────────────┘
                            │ (JSON Broadcast)
                            ▼
                 ┌───────────────────────┐
                 │    Frontend UI Client │
                 └───────────────────────┘
```

1.  **Ingestion**: Alice Blue WebSocket pushes a tick message containing the exchange token and last price.
2.  **Translation**: `AliceBlueProvider` catches the tick, calls `zebu_token_to_canonical` using the memory map, and parses fields into the normalized format.
3.  **Coordination**: The normalized quote is routed through `QuoteCoordinator.ingest_equity_quote`.
    *   If the price or volume changed, the coordinator:
        1.  Updates the process-local `SmartCache`.
        2.  Writes to Redis (under `alphasync:price:{symbol}` and the `alphasync:price:all` hash).
        3.  Publishes a `PRICE_UPDATED` event to the internal `EventBus`.
    *   If no values changed, it updates `SmartCache` but skips the Redis write and EventBus publication.
4.  **Distribution**: The `WebsocketManager` listens to the EventBus. When a `PRICE_UPDATED` event matches a client subscription, it serializes the quote and sends it over a JSON WebSocket to the browser.
5.  **Fallback Sweeper**: The background `MarketDataWorker` runs adaptive sweeps (every 3 seconds during open hours, 60 seconds when closed) to pull quotes in batches of 16 using `get_batch_quotes()` over REST for symbols that haven't received WebSocket updates, updating Redis and the EventBus.

---

## 7. Charts & OHLCV Candle Generation

Intraday charts are built dynamically by the backend using ticks and persisted to Redis.

```
WebSocket Ticks ──► MarketDataWorker ──► Aggregate 1m Candle ──► Aggregate 5m Candle
                                                │                       │
                                                ▼                       ▼
                                           Redis: 1d 1m            Redis: 5d 5m
                                          (history key)           (history key)
```

### A. Candle Aggregation
The `MarketDataWorker` monitors tick updates and aggregates them into time-based bars:
*   **Intraday Intervals**: Supports `1m` and `5m` candles.
*   **Volume Handling**: To track volume correctly across candle boundaries, the worker records the session-cumulative volume from Alice Blue ticks. It computes:
    $$\text{Volume}_{\text{candle}} = \text{Cumulative Volume}_{\text{current}} - \text{Cumulative Volume}_{\text{candle\_start}}$$
*   **Key Fields**: The worker updates the candle structure:
    *   `time`: Start epoch of the bucket (e.g., rounded down to nearest 60s for 1m).
    *   `open`: First price in the bucket.
    *   `high` / `low`: Maximum and minimum prices observed in the bucket.
    *   `close`: Latest price in the bucket.

### B. Redis Persistence & Buffering
*   **1m Candles**: Accumulated in-memory and flushed to Redis every 15 seconds.
    *   Key: `alphasync:history:{symbol}:1d:1m`
    *   Retention limit: **480 candles** (~1 trading day).
*   **5m Candles**: Flushed to Redis:
    *   Key: `alphasync:history:{symbol}:5d:5m`
    *   Retention limit: **192 candles** (~4 trading days).
*   **derived Intervals**: At the persistence interval, 1m candles are mathematically aggregated to build `2m` and `3m` candles, which are written to Redis to support custom client zoom intervals.

### C. Rest Chart History Fallback
When the market is closed or the user requests EOD/historical charts extending past the Redis buffers:
*   **REST Call**: A POST request is sent to the official historical endpoint:
    ```
    POST https://a3.aliceblueonline.com/open-api/od/ChartAPIService/api/chart/history
    Authorization: Bearer <session_token>
    Content-Type: application/json
    ```
*   **Httpx Headers**: The headers must use `Authorization: Bearer <session_token>`. Unlike other API calls, the `userId` prefix is omitted.
*   **Payload Requirements**:
    ```json
    {
      "token": "<token_id>",
      "resolution": "1",
      "from": "<epoch_ms_from>",
      "to": "<epoch_ms_to>",
      "exchange": "<exchange>"
    }
    ```
*   **Timestamps & Resampling**: Timestamps must be in **milliseconds** (epoch $\times$ 1000). The resolution defaults to `"1"` (1 minute) for intraday data. If the user requests a larger bucket (e.g., `15m`), the client fetches the 1-minute historical bars and resamples them in-process using `_resample_candles()`.

---

## 8. Futures & Options (F&O) Data Pipeline

Alice Blue derivatives data uses the shared futures service pipeline within `futures_service.py`:

*   **Token Mapping**: Alice Blue and Zebu share standard NSE exchange token definitions. Mappings parsed from the contract masters (such as `NFO_symbols.txt.zip`) are loaded into the shared mapping index.
*   **Live Resolution**: If a derivatives token is requested but missing, `AliceBlueProvider` fetches the exchange contract master zip from the Alice Blue REST CDN (`https://v2api.aliceblueonline.com/restpy/static/contract_master/V2/NFO`) to resolve and register the token.
*   **Event Emitter**: When WebSocket ticks arrive for NFO/BFO tokens, the provider converts them to a `FUTURES_QUOTE` schema containing open interest (`oi`), average price (`ap`), bid/ask spread, and publishes them to the EventBus.

---

## 9. Simulated Order Placement & Safety Guards

```
               [Outgoing API Call / WS Message]
                              │
                              ▼
                ┌───────────────────────────┐
                │   BrokerSafetyGuard       │
                └─────────────┬─────────────┘
                              │
            ┌─────────────────┴─────────────────┐
            ▼                                   ▼
  [Match Whitelist / Safe]           [Match Blocked / Order API]
            │                                   │
            ▼                                   ▼
     Allow Call to Zebu/AB               Block Call & Raise
                                         BrokerSafetyError
                                      (Safe simulated execution)
```

### A. The Safety Whitelist (Zero Real Trade Risk)
AlphaSync is designed to prevent real-world trading losses. The `BrokerSafetyGuard` intercepts outgoing network traffic.
*   **Safe API Whitelist**: Only read-only and authentication endpoints are permitted:
    `ALLOWED_ENDPOINTS = [/QuickAuth, /UserDetails, /GetQuotes, /SearchScrip, /TPSeries]`
*   **Blocked Dangerous Patterns**: Any path containing trade execution keywords is blocked:
    `BLOCKED_PATTERNS = [placeorder, modifyorder, cancelorder, funds, transfer, squareoff]`
*   **WS Safety Guard**: Outgoing WS messages are inspected by `is_safe_websocket_message()`. Messages with types related to placing or modifying orders (`o`, `O`, `om`) are blocked.
*   *Because Alice Blue uses standard HTTP requests for REST, its calls do not route through Zebu-specific safety code, but order placement is handled strictly within the backend's local database simulation.*

### B. Simulated Order Placement Flow
All order placements are simulated locally using PostgreSQL:

1.  **Request Ingestion**: The route `POST /api/orders` sends the order parameters to `trading_engine.place_order()`.
2.  **Price Verification**: The engine fetches the latest price from the Redis cache using `get_quote_safe()`. For `LIMIT` or `STOP_LOSS` orders, it forces a fresh check to prevent fills based on stale UI prices.
3.  **Risk Engine Check**: The order is validated against local risk parameters (e.g., maximum order size constraints, wash trading blocks, and daily loss limits).
4.  **Capital & Margin Check**:
    *   For `CNC` (delivery) equity buy orders, the engine checks if the required capital is available in the local portfolio.
    *   For `MIS` (intraday) orders, the engine applies a **5x leverage factor**, requiring only 20% of the total order value as margin.
    *   For futures orders, the margin is calculated via the SPAN-like engine in `futures_margin_engine.py` (approx. 12% for indices, 20-30% for stocks).
5.  **Execution Logic**:
    *   **MARKET**: Executed immediately at the current tick price.
    *   **LIMIT**: Stays `OPEN` in the database. Fills only if a tick arrives where $\text{LTP} \le \text{Limit Price}$ (for buys) or $\text{LTP} \ge \text{Limit Price}$ (for sells).
6.  **DB Position Updates**: Fills trigger capital updates in `portfolios` and modify positions in `holdings` (for equities) or `futures_positions` (for derivatives). Exit orders that close positions automatically cancel any orphaned stop-loss or take-profit legs.

---

## 10. Database Schema (PostgreSQL)

AlphaSync uses the following tables to manage Alice Blue sessions and simulation states:

### `broker_accounts`
Stores the connection state and credentials for Alice Blue sessions.

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | `UUID` | Primary key |
| `user_id` | `UUID` | Foreign key referencing `users.id` |
| `broker` | `String(32)` | Hardcoded to `"aliceblue"` |
| `broker_user_id` | `String(128)` | The Alice Blue client ID (e.g., `AB12345`) |
| `access_token_enc` | `Text` | AES-256-GCM encrypted `userSession` |
| `refresh_token_enc` | `Text` | Encrypted refresh token (not used by Alice Blue) |
| `token_expiry` | `DateTime` | Expiration time (typically 8 hours from login) |
| `is_active` | `Boolean` | Flag indicating if the session is active |
| `credentials_enc` | `Text` | AES-256-GCM encrypted JSON with App Code, password, and TOTP key |
| `extra_data_enc` | `Text` | Encrypted JSON containing profile metadata |
| `connected_at` | `DateTime` | Timestamp of the connection |

### `orders` / `futures_orders`
Stores details of simulated trades.

*   **Key Fields**: `user_id`, `symbol`, `exchange` (`NSE`/`MCX`/`NFO`), `side` (`BUY`/`SELL`), `order_type` (`MARKET`/`LIMIT`/`STOP_LOSS`/`TAKE_PROFIT`), `quantity`, `price`, `trigger_price`, `status` (`OPEN`/`FILLED`/`CANCELLED`), `filled_price`, and `executed_at`.

### `holdings` / `futures_positions`
Tracks active open positions in the simulation.

*   **Key Fields**: `portfolio_id`, `symbol`, `product_type` (`MIS`/`CNC`), `quantity` (positive for long, negative for short), `avg_price` (average entry price), `current_price` (marked-to-market), and `unrealized_pnl`.
