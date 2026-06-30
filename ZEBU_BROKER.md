# Zebu (MYNT) Broker Integration & Architecture

This document provides a detailed technical explanation of the Zebu (MYNT) broker integration within the AlphaSync platform. It covers the end-to-end lifecycle—from initial connection and authentication, real-time WebSocket tick ingestion, data caching layers, PostgreSQL schemas, and historical data retrieval, to simulated order placement and the system safety guards.

---

## 1. Protocol & Integration Overview

AlphaSync integrates with Zebu (MYNT) using the **NorenOMS** protocol. This integration consists of two main channels:
*   **REST API Channel**: Used for initial authentication, session validation, historical candle queries, and symbol resolution on-demand.
*   **WebSocket Channel**: A persistent streaming connection used exclusively to ingest real-time market ticks (touchline feed).

### Base Connection Endpoints
*   **WebSocket URL**: `wss://ws1.zebull.in/NorenWS/` (Configured via `ZEBU_WS_URL`)
*   **REST API Base**: `https://go.mynt.in/NorenWClientTP` (Configured via `ZEBU_API_URL`, with fallbacks to `https://go.mynt.in/NorenWClientAPI` / `https://go.mynt.in/NorenWClient`)

---

## 2. Authentication Flows & Session Lifecycle

AlphaSync supports multiple connection pathways for Zebu, providing flexibility for both standard browser logins and automated background agents.

```
       [Standard OAuth Flow]                          [Headless QuickAuth Flow]
                 │                                               │
 1. GET /api/broker/zebu/connect                         1. POST /api/broker/zebu/login
                 │                                               │
 2. Redirect User to MYNT Login                          2. Retrieve Saved App Credentials
                 │                                          (Trading Pwd + DOB/PAN)
 3. User Login & Success Redirect                                │
                 │                                       3. Calculate SHA-256 AppKey
 4. GET /api/broker/callback/zebu?code=...                  appkey = sha256(uid + api_key)
                 │                                               │
 5. Exchange Code via REST /GenAcsTok                    4. POST /QuickAuth REST Endpoint
    (jData payload with Checksum)                                │
                 │                                               │
                 └──────────────┬────────────────────────────────┘
                                │
                     [Success: Get susertoken]
                                │
                  5. Encrypt (AES-256-GCM) & Store
                     in PostgreSQL (broker_accounts)
```

### A. OAuth 2.0 Web Authentication
1.  **Authorization Redirect**: The user initiates connection via `GET /api/broker/zebu/connect`. The system generates a state token and redirects the browser to the MYNT authorization page.
2.  **Callback Processing**: Upon successful login, the broker redirects to `GET /api/broker/callback/zebu?code=...`.
3.  **Token Exchange**: The backend exchanges the authorization code by calling the `/GenAcsTok` REST endpoint with a POST request. The request payload is structured as `jData={payload}` where the payload is:
    ```json
    {
      "code": "<auth_code>",
      "checksum": "sha256(client_id + client_secret + auth_code)"
    }
    ```
4.  **Token Extraction**: Zebu returns a response containing `susertoken` (or `access_token`). Zebu's user ID (`uid`) is extracted directly from the response or decoded from the JWT payload.

### B. Headless QuickAuth (Zero-Click Login)
For system-level workers (or users requesting automated session restore), AlphaSync implements a headless `QuickAuth` flow utilizing saved credentials:
1.  **AppKey Generation**: The system builds a secure hash:
    $$\text{AppKey} = \text{SHA256}(\text{client\_id} + "|" + \text{api\_key})$$
2.  **QuickAuth Request**: A POST request is sent to the `/QuickAuth` REST endpoint:
    ```
    POST /QuickAuth
    Content-Type: application/x-www-form-urlencoded
    jData={"apkversion":"1.0.0","uid":"<user_id>","pwd":"<sha256_pwd>","factor2":"<dob_or_pan>","vc":"<vendor_code>","appkey":"<appkey>","imei":"alphasync","source":"API"}
    ```
3.  **Token Retrieval**: The response yields a valid `susertoken` to authenticate the WebSocket feed.

### C. Session Management & Decryption
*   **Database Storage**: Authenticated session details are stored in the PostgreSQL table `broker_accounts`. To protect user credentials and tokens, sensitive fields are encrypted at rest.
*   **Encryption Standard**: Cryptographic operations are handled by [broker_crypto.py](file:///d:/VIANMAX%20DEV%20TEAM/GITHUB%20-%20DEMO001/NEW%20MODULE%20-%20ALPHASYNC/3/demo.001/backend/services/broker_crypto.py) using **AES-256-GCM**.
    *   Encryption Key: Derived via **HKDF-SHA256** from the global system key `settings.ENCRYPTION_KEY`.
    *   Encrypted fields: `access_token_enc`, `refresh_token_enc`, `credentials_enc` (which holds api_key, api_secret, trading_password, and factor2 in an encrypted JSON object), and `extra_data_enc`.
*   **Session Lifecycle**: Managed by `BrokerSessionManager` (a singleton). Sessions are restored from the database on app startup. The health daemon runs a background check every 5 minutes (`start_health_check`) to invalidate expired tokens.

---

## 3. WebSocket Connection & Tick Ingestion

AlphaSync maintains a per-user persistent WebSocket client to ingest market ticks.

### A. Connection Handshake & Authentication
Once the TCP socket to `wss://ws1.zebull.in/NorenWS/` is open, an authentication handshake message must be sent within 10 seconds:
```json
{
  "t": "c",
  "uid": "<client_id>",
  "actid": "<client_id>",
  "susertoken": "<decrypted_session_token>",
  "accesstoken": "<decrypted_session_token>",
  "source": "API"
}
```
Zebu responds with a confirmation message. If authentication is successful, the message has the form `{"t":"cf", "s":"OK"}`.

### B. Heartbeat Monitoring
The provider spins up a background heartbeat task `_heartbeat_loop()`:
*   **Ping Interval**: A heartbeat request `{"t": "h"}` is sent every 30 seconds.
*   **Ping Frame**: The provider calls `ws.ping()` to send a low-level WebSocket ping frame.
*   **Pong Timeout**: The provider expects a pong response within 10 seconds. If a timeout occurs, it triggers a reconnection sequence.

### C. Reconnection Protocol
If the connection drops or the heartbeat fails, the provider enters a reconnection loop:
*   **Strategy**: Exponential backoff with jitter.
*   **Parameters**: Base delay = 1.0s, backoff factor = 2.0, max delay capped at 60s.
*   **Max Attempts**: Capped at 50 consecutive failures. If reached, the provider changes status to `ProviderStatus.ERROR` and requires manual intervention.
*   **State Recovery**: Upon reconnection, the provider automatically resubscribes to all symbols recorded in its active subscriptions set.

---

## 4. Symbol Mapping & Data Normalization

Zebu uses token-based routing. To exchange data between Zebu and AlphaSync, symbols must be translated.

### A. Symbol Mapper Mechanics
Managed by [symbol_mapper.py](file:///d:/VIANMAX%20DEV%20TEAM/GITHUB%20-%20DEMO001/NEW%20MODULE%20-%20ALPHASYNC/3/demo.001/backend/providers/symbol_mapper.py):
*   **AlphaSync Canonical Format**: Standardized symbols like `RELIANCE.NS` (equities), `^NSEI` (indices), or `GOLD` (commodities).
*   **Zebu Format**: Mapped to Exchange + Token ID (e.g., Exchange: `NSE`, Token: `2885` for Reliance).
*   **Initialization**: At startup, `initialize_futures()` or contract loaders download zip archives of Zebu master files (e.g., `NFO_symbols.txt.zip`). Mappings are parsed and loaded into local dictionaries:
    *   `_ZEBU_SYMBOL_MAP`: Canonical → `{"trading_symbol", "token", "exchange"}`
    *   `_TOKEN_TO_CANONICAL`: `EXCHANGE|token` → Canonical Symbol
*   **On-Demand Resolution**: If a symbol is missing, the provider queries `/SearchScrip` over REST to resolve the token ID and stores it dynamically in the symbol map.

### B. Tick Normalization
Incoming raw NorenWS WebSocket tick feeds (type `tk` or `tf`) are mapped into a unified dictionary structure:

| Zebu WS Field | AlphaSync Unified Schema | Description |
| :--- | :--- | :--- |
| `tk` | `token` / `instrument_token` | Exchange numeric token ID |
| `e` | `exchange` | Exchange (NSE, BSE, NFO, MCX) |
| `ts` | `name` | Trading symbol description |
| `lp` | `price` / `ltp` | Last traded price (converted to float) |
| `v` | `volume` | Cumulative trading volume (handled dynamically) |
| `o`, `h`, `l` | `open`, `high`, `low` | Session open, high, and low prices |
| `c` | `close` / `prev_close` | Previous day's close price |
| `bp1`, `sp1` | `bid_price`, `ask_price` | Best bid and ask prices |
| `bq1`, `sq1` | `bid_qty`, `ask_qty` | Best bid and ask quantities |
| `oi` | `oi` | Open Interest (for derivative contracts) |
| `ft` / `ltt` | `last_trade_time` / `timestamp` | Timestamp (ISO-8601 UTC) |

*Note: For update ticks (`tf`), Zebu frequently omits unchanged fields. The parser merges incoming ticks with the process-local cache (`_price_cache`) to avoid losing static metrics like `prev_close` or `open`.*

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
                  │   Zebu WebSocket     │
                  └──────────┬───────────┘
                             │ (Tick: Exchange|Token + LP)
                             ▼
                  ┌──────────────────────┐
                  │    ZebuProvider      │
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

1.  **Ingestion**: Zebu WebSocket pushes a tick message containing the exchange token and last price.
2.  **Translation**: `ZebuProvider` catches the tick, calls `zebu_token_to_canonical` using the memory map, and parses fields into the normalized format.
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
*   **Volume Handling**: To track volume correctly across candle boundaries, the worker records the session-cumulative volume from Zebu ticks. It computes:
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
*   **REST Call**: A POST request is sent to Zebu's `/TPSeries` (intraday) or `/EODChartData` (daily) API.
*   **Formatting**: Timestamps are sent and returned as epoch seconds.
*   **Resampling**: Zebu's API only supports `1` minute intraday resolution. If a user requests a custom interval (e.g., 15m), AlphaSync downloads 1-minute historical bars and resamples them inside the provider using `_resample_candles()`.

---

## 8. Futures & Options (F&O) Data Pipeline

Zebu derivatives data uses a distinct pipeline within `futures_service.py` to prevent equity cash feeds from mixing with futures instruments.

*   **Master Load**: At startup, `initialize_futures()` downloads F&O master files (e.g., `NFO_symbols.txt.zip` from Zebu's CDN).
*   **Parsing Details**: The file is unzipped, and the service filters rows matching `FUTIDX` (index futures) or `FUTSTK` (stock futures).
*   **Underlying Matching**: The service extracts the underlying symbol using a prefix matching algorithm:
    *   It tests against known indices (`NIFTY`, `BANKNIFTY`, `FINNIFTY`) in descending length order.
    *   If no index matches, it runs a regular expression: `^([A-Z&]+?)(\d{1,2}[A-Z]{3}\d{2,4})` to extract the stock prefix (e.g., `RELIANCE` from `RELIANCE24APR26F`).
*   **Chain Classification**: Sorted by expiry date (nearest first).
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
     Allow Call to Zebu                  Block Call & Raise
                                         BrokerSafetyError
                                      (Safe simulated execution)
```

### A. The Broker Safety Guard (Zero Real Trade Risk)
AlphaSync is designed to prevent real-world trading losses. The [broker_safety.py](file:///d:/VIANMAX%20DEV%20TEAM/GITHUB%20-%20DEMO001/NEW%20MODULE%20-%20ALPHASYNC/3/demo.001/backend/services/broker_safety.py) middleware intercepts all outgoing network traffic to Zebu.
*   **Safe API Whitelist**: Only read-only and authentication endpoints are permitted:
    `ALLOWED_ENDPOINTS = [/QuickAuth, /UserDetails, /GetQuotes, /SearchScrip, /TPSeries]`
*   **Blocked Dangerous Patterns**: Any path containing trade execution keywords is blocked:
    `BLOCKED_PATTERNS = [placeorder, modifyorder, cancelorder, funds, transfer, squareoff]`
*   **WS Safety Guard**: Outgoing WS messages are inspected by `is_safe_websocket_message()`. Messages with types related to placing or modifying orders (`o`, `O`, `om`) are blocked.
*   *If a blocked call is intercepted, the guard raises `BrokerSafetyError` and logs a critical alert.*

### B. Simulated Order Placement Flow
Because real order execution is blocked, the `trading_engine` simulates all orders using PostgreSQL:

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

AlphaSync uses the following tables to manage Zebu sessions and simulation states:

### `broker_accounts`
Stores the connection state and credentials for Zebu sessions.

| Column | Type | Description |
| :--- | :--- | :--- |
| `id` | `UUID` | Primary key |
| `user_id` | `UUID` | Foreign key referencing `users.id` |
| `broker` | `String(32)` | Hardcoded to `"zebu"` |
| `broker_user_id` | `String(128)` | The Zebu client ID (e.g., `ZB12345`) |
| `access_token_enc` | `Text` | AES-256-GCM encrypted `susertoken` |
| `refresh_token_enc` | `Text` | Encrypted refresh token (not used by Zebu) |
| `token_expiry` | `DateTime` | Expiration time (typically 8 hours from login) |
| `is_active` | `Boolean` | Flag indicating if the session is active |
| `credentials_enc` | `Text` | AES-256-GCM encrypted JSON with QuickAuth secrets |
| `extra_data_enc` | `Text` | Encrypted JSON containing profile metadata |
| `connected_at` | `DateTime` | Timestamp of the connection |

### `orders` / `futures_orders`
Stores details of simulated trades.

*   **Key Fields**: `user_id`, `symbol`, `exchange` (`NSE`/`MCX`/`NFO`), `side` (`BUY`/`SELL`), `order_type` (`MARKET`/`LIMIT`/`STOP_LOSS`/`TAKE_PROFIT`), `quantity`, `price`, `trigger_price`, `status` (`OPEN`/`FILLED`/`CANCELLED`), `filled_price`, and `executed_at`.

### `holdings` / `futures_positions`
Tracks active open positions in the simulation.

*   **Key Fields**: `portfolio_id`, `symbol`, `product_type` (`MIS`/`CNC`), `quantity` (positive for long, negative for short), `avg_price` (average entry price), `current_price` (marked-to-market), and `unrealized_pnl`.
