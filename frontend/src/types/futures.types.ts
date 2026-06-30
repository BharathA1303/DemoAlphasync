/**
 * Futures Data & WebSocket Types
 * Complete type definitions for the Futures page and real-time data feeds
 */

/**
 * Futures Contract Metadata
 */
export interface FuturesContract {
  contract_symbol: string; // e.g., "RELIANCE25MAR2026FUT"
  token?: string; // Zebu token ID
  exchange: string; // "NSE"
  expiry_date: string; // ISO format: "2026-03-25"
  expiry_label: "Near" | "Mid" | "Far";
  days_to_expiry: number;
  lot_size: number; // Minimum order quantity
  tick_size: number; // Minimum price movement
  instrument_type: "FUTIDX" | "FUTSTK"; // Index futures or stock futures
}

/**
 * Futures Quote (live price data)
 */
export interface FuturesQuote {
  contract_symbol: string;
  ltp: number | null; // Last traded price
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  change: number; // Absolute price change
  change_pct: number; // Percentage change
  volume: number; // Total trade volume
  oi: number; // Open interest
  oi_change: number | null; // OI change vs previous close
  bid: number | null;
  ask: number | null;
  bid_depth?: number | null; // Volume at bid side
  ask_depth?: number | null; // Volume at ask side
  vwap: number | null; // Volume weighted average price
  timestamp: number; // Unix timestamp (seconds)
  market_open: boolean;
  available: boolean; // True if data is available, false if unavailable
}

/**
 * Futures OHLCV Candle (for sparkline)
 */
export interface FuturesCandle {
  timestamp: string; // ISO format or Unix timestamp
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

/**
 * Underlying Spot Price (for basis calculation)
 */
export interface SpotQuote {
  symbol: string; // "RELIANCE.NS" or "^NSEI"
  ltp: number | null;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  change: number; // Rs change
  change_pct: number; // % change
  volume: number;
  timestamp: number;
  market_open: boolean;
  available: boolean;
}

/**
 * API Response: List of contracts
 */
export interface ContractsResponse {
  contracts: FuturesContract[];
  symbol: string;
  found: boolean;
  market_open: boolean;
}

/**
 * API Response: Contract quote
 */
export interface QuoteResponse extends FuturesQuote {
  // Extends FuturesQuote
}

/**
 * API Response: Contract history
 */
export interface HistoryResponse {
  contract_symbol: string;
  interval: string; // "5m", "1h", "1d", etc.
  candles: FuturesCandle[];
  market_open: boolean;
}

/**
 * WebSocket Event: Subscribe to futures contract
 */
export interface SubscribeFuturesMessage {
  type: "subscribe_futures";
  contract: string; // Zebu contract symbol
}

/**
 * WebSocket Event: Unsubscribe from futures contract
 */
export interface UnsubscribeFuturesMessage {
  type: "unsubscribe_futures";
  contract: string;
}

/**
 * WebSocket Event: Futures quote update
 */
export interface FuturesQuoteEvent {
  type: "futures_quote";
  contract: string; // Zebu contract symbol
  data: FuturesQuote;
}

/**
 * Page State: No symbol selected
 */
export interface EmptyState {
  status: "empty";
}

/**
 * Page State: Loading (initial data fetch)
 */
export interface LoadingState {
  status: "loading";
}

/**
 * Page State: Ready (data loaded, ready to display)
 */
export interface ReadyState {
  status: "ready";
  selectedSymbol: string;
  selectedContract: FuturesContract | null;
  contracts: FuturesContract[];
  quote: FuturesQuote | null;
  history: FuturesCandle[];
  spotPrice: SpotQuote | null;
}

/**
 * Page State: Error (data fetch failed)
 */
export interface ErrorState {
  status: "error";
  message: string;
}

/**
 * Page State type union
 */
export type PageState = EmptyState | LoadingState | ReadyState | ErrorState;

/**
 * OI & Price relationship for sentiment
 */
export type SentimentType =
  | "long-buildup" // OI up + Price up
  | "short-buildup" // OI up + Price down
  | "short-covering" // OI down + Price up
  | "long-unwinding"; // OI down + Price down

/**
 * Market Sentiment Data
 */
export interface MarketSentiment {
  type: SentimentType;
  label: string; // "Long build-up", "Short covering", etc.
  color: "green" | "red" | "amber";
  oi_trend: "up" | "down";
  price_trend: "up" | "down";
  oi_current: number;
  oi_previous: number;
  price_current: number;
  price_previous: number;
}

/**
 * Derived Metrics for Right Panel
 */
export interface DerivedMetrics {
  notionalValue: number; // lot_size × ltp
  basis: number; // futures_ltp - spot_ltp
  basis_pct: number; // basis as % of spot price
  costOfCarry: number; // annualized cost
  daysToExpiry: number;
  volatilityLevel: "low" | "medium" | "high"; // Derived from volume/oi
}

/**
 * WebSocket Manager State
 */
export interface WebSocketState {
  status: "connected" | "disconnected" | "reconnecting" | "stale";
  lastMessageAt: number | null; // Unix timestamp (ms)
  reconnectAttempt: number;
  contract: string | null; // Currently subscribed contract
  error: string | null;
}

/**
 * Search Result for Symbol Search
 */
export interface SymbolSearchResult {
  symbol: string;
  name: string;
  exchange: "NSE" | "BSE";
  type: "equity" | "index";
}

/**
 * Futures Order (simulated, local DB only)
 */
export interface FuturesOrder {
  id: string;
  contract_symbol: string;
  order_type: "MARKET" | "LIMIT" | "STOP_LOSS" | "STOP_LOSS_LIMIT";
  side: "BUY" | "SELL";
  quantity: number;
  price: number | null; // For limit orders
  trigger_price: number | null; // For stop-loss orders
  filled_quantity: number;
  filled_price: number | null;
  status: "PENDING" | "OPEN" | "FILLED" | "CANCELLED" | "EXPIRED" | "REJECTED";
  tag: string | null;
  created_at: string; // ISO timestamp
  executed_at: string | null; // ISO timestamp
}

/**
 * Futures Position (open position in a contract)
 */
export interface FuturesPosition {
  id: string;
  contract_symbol: string;
  quantity: number; // Positive = long, negative = short
  avg_entry_price: number;
  current_price: number;
  unrealized_pnl: number; // Unrealized profit/loss
  realized_pnl: number; // Realized profit/loss from closed positions
  updated_at: string; // ISO timestamp
}

/**
 * Place Order Request
 */
export interface PlaceFuturesOrderRequest {
  contract_symbol: string;
  side: "BUY" | "SELL";
  order_type: "MARKET" | "LIMIT" | "STOP_LOSS" | "STOP_LOSS_LIMIT";
  quantity: number;
  price?: number;
  trigger_price?: number;
  tag?: string;
}
