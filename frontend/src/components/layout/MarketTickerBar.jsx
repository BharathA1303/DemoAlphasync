// MarketTickerBar.jsx
import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useSyncExternalStore } from "react";
import { useMarketIndicesStore } from "../../stores/useMarketIndicesStore";
import { useMarketStore } from "../../store/useMarketStore";
import { marketSessionManager } from "../../market/MarketSessionManager";
import { cn } from "../../utils/cn";
import { formatPrice, formatPercent } from "../../utils/formatters";
import { resolveTickerItem } from "../../market/UnifiedPriceResolver";
import { getEODQuoteCache } from "../../market/EODReconciliationEngine";
import {
  getSessionCloseCache,
  subscribeSessionClosePrices,
} from "../../market/SessionClosePriceAuthority";
import { TrendingUp, TrendingDown } from "lucide-react";

function TickerItem({ item, onClick, showSeparator }) {
  const isPositive = (item.change ?? 0) >= 0;
  const isIndex = item.kind === "index";
  const isClickable = !isIndex;

  return (
    <>
      <div
        onClick={isClickable ? () => onClick(item) : undefined}
        className={cn(
          "flex items-center gap-2 flex-shrink-0 px-3 py-0.5 rounded transition-colors duration-150",
          isClickable
            ? "cursor-pointer hover:bg-overlay/[0.06] active:scale-95 group"
            : "cursor-default",
        )}
        title={isClickable ? `Open ${item.name} in Terminal` : undefined}
        aria-label={`${item.name} ${formatPrice(item.price, 2)} ${isPositive ? "up" : "down"} ${formatPercent(item.change_percent, 2)}`}
      >
        <span
          className={cn(
            "text-xs font-medium whitespace-nowrap transition-colors",
            isIndex ? "text-gray-500" : "text-gray-500",
            isClickable && "group-hover:text-primary-600",
          )}
        >
          {item.name}
        </span>
        <span className="text-xs font-price font-medium text-heading tabular-nums">
          {formatPrice(item.price, 2)}
        </span>
        <span
          className={cn(
            "flex items-center gap-0.5 text-xs font-price tabular-nums font-normal",
            isPositive ? "text-emerald-600" : "text-red-500",
          )}
        >
          {isPositive ? "▲" : "▼"} {formatPercent(item.change_percent, 2)}
        </span>
      </div>
      {showSeparator && (
        <span
          className="text-gray-600 mx-3 flex-shrink-0 select-none"
          aria-hidden="true"
        >
          │
        </span>
      )}
    </>
  );
}

const normalizeTickerSymbol = (symbol = "") => {
  const raw = String(symbol || "").trim().toUpperCase();
  if (!raw) return "";
  if (raw.startsWith("^") || raw.endsWith(".NS") || raw.endsWith(".BO")) return raw;
  return `${raw}.NS`;
};

const resolveLiveTickerQuote = (item, liveQuotes) => {
  const symbol = String(item?.symbol || "").trim();
  const base = symbol.replace(/\.(NS|BO)$/i, "");
  const normalized = normalizeTickerSymbol(symbol);

  return (
    liveQuotes?.[symbol] ||
    liveQuotes?.[normalized] ||
    liveQuotes?.[base] ||
    liveQuotes?.[base.toUpperCase()] ||
    null
  );
};

/**
 * Horizontally scrolling ticker bar (marquee) showing indices + stocks.
 * - Clicking any stock navigates to /terminal?symbol=SYMBOL.NS
 * - Marquee pauses on hover so the user can read/click comfortably
 * - Duplicates content so scroll loops seamlessly
 */
export default function MarketTickerBar() {
  const navigate = useNavigate();
  const tickerItems = useMarketIndicesStore((s) => s.tickerItems);
  const indices = useMarketIndicesStore((s) => s.indices);
  const isLoading = useMarketIndicesStore((s) => s.isLoading);
  const liveQuotes = useMarketStore((s) => s.symbols);
  const startPolling = useMarketIndicesStore((s) => s.startPolling);
  const stopPolling = useMarketIndicesStore((s) => s.stopPolling);
  const [paused, setPaused] = useState(false);
  const [tooltip, setTooltip] = useState(null); // { name, x }
  const tooltipTimeout = useRef(null);

  const sessionTick = useSyncExternalStore(
    (cb) => marketSessionManager.subscribe(cb),
    () => marketSessionManager.getSnapshot().fetchedAt,
    () => 0,
  );

  // Poll ticker more often when closed so official EOD replaces stale snapshot prices.
  useEffect(() => {
    const snap = marketSessionManager.getSnapshot();
    stopPolling();
    startPolling(snap.isOpen ? 120_000 : 30_000);
    if (!snap.isOpen) {
      import('../../market/sessionClosePrefetch').then(({ prefetchSessionClosePrices }) => {
        import('../../market-v2/tickerHotSymbols').then(({ TICKER_HOT_SYMBOLS }) => {
          prefetchSessionClosePrices(TICKER_HOT_SYMBOLS);
        });
      });
    }
    return () => stopPolling();
  }, [startPolling, stopPolling, sessionTick]);
  const lastQuoteAt = useMarketStore((s) => s.lastQuoteAt);
  const sessionCloseKey = useSyncExternalStore(
    subscribeSessionClosePrices,
    () => Object.keys(getSessionCloseCache()).length,
    () => 0,
  );
  const eodQuotes = useMemo(() => {
    const session = getSessionCloseCache();
    const eod = getEODQuoteCache();
    return { ...eod, ...session };
  }, [sessionTick, lastQuoteAt, tickerItems.length, sessionCloseKey]);

  const items = useMemo(() => {
    const sourceItems = tickerItems.length > 0 ? tickerItems : indices;
    const marketClosed = !marketSessionManager.getSnapshot().isOpen;
    return sourceItems.map((item) =>
      resolveTickerItem(item, marketClosed ? {} : liveQuotes, eodQuotes),
    );
  }, [tickerItems, indices, liveQuotes, eodQuotes, sessionTick, sessionCloseKey]);

  // Show empty bar instead of null to prevent unmount/remount flicker
  if (items.length === 0) {
    return <div className="h-7 bg-surface-900/80 border-b border-edge/5" />;
  }

  const handleClick = (item) => {
    // Ensure symbol ends with .NS for NSE stocks
    const symbol = item.symbol?.endsWith(".NS")
      ? item.symbol
      : `${item.symbol}.NS`;
    navigate(`/terminal?symbol=${encodeURIComponent(symbol)}`);
  };

  const handleMouseEnter = (item, e) => {
    if (item.kind === "index") return;
    clearTimeout(tooltipTimeout.current);
    setTooltip({
      name: `Click to open ${item.name} in Terminal`,
      x: e.clientX,
    });
  };

  const handleMouseLeave = () => {
    tooltipTimeout.current = setTimeout(() => setTooltip(null), 150);
  };

  return (
    <div
      className="h-7 bg-surface-900/80 border-b border-edge/5 overflow-hidden flex items-center relative"
      onMouseEnter={() => setPaused(true)}
      onMouseLeave={() => {
        setPaused(false);
        setTooltip(null);
      }}
    >
      {/* Fade edges */}
      <div className="absolute left-0 top-0 bottom-0 w-8 bg-gradient-to-r from-surface-900/90 to-transparent z-10 pointer-events-none" />
      <div className="absolute right-0 top-0 bottom-0 w-8 bg-gradient-to-l from-surface-900/90 to-transparent z-10 pointer-events-none" />

      {/* Floating tooltip */}
      {tooltip && (
        <div
          className="fixed top-10 z-50 px-2.5 py-1.5 rounded-lg bg-surface-800 border border-primary-500/20 text-[11px] text-primary-500 font-medium shadow-xl pointer-events-none whitespace-nowrap"
          style={{ left: Math.min(tooltip.x, window.innerWidth - 240) }}
        >
          {tooltip.name}
        </div>
      )}

      {/* Marquee track — two copies for seamless loop */}
      <div
        className="ticker-marquee flex items-center"
        style={{
          animationPlayState: paused ? "paused" : "running",
          '--ticker-duration': `${Math.max(20, items.length * 3)}s`,
        }}
      >
        {/* Copy A */}
        <div className="ticker-track flex items-center">
          {items.map((item, i) => (
            <div
              key={`a-${i}`}
              className="flex items-center"
              onMouseEnter={(e) => handleMouseEnter(item, e)}
              onMouseLeave={handleMouseLeave}
            >
              <TickerItem
                item={item}
                onClick={handleClick}
                showSeparator={i < items.length - 1}
              />
            </div>
          ))}
        </div>
        {/* Copy B — aria-hidden duplicate for seamless loop */}
        <div className="ticker-track flex items-center" aria-hidden="true">
          {items.map((item, i) => (
            <div
              key={`b-${i}`}
              className="flex items-center"
              onMouseEnter={(e) => handleMouseEnter(item, e)}
              onMouseLeave={handleMouseLeave}
            >
              <TickerItem
                item={item}
                onClick={handleClick}
                showSeparator={i < items.length - 1}
              />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
