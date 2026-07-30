import { memo } from 'react';
import useUnifiedFuturesStore from '../../stores/useUnifiedFuturesStore';
import { useMarketStore } from '../../store/useMarketStore';
import { cn } from '../../utils/cn';
import { Wifi, WifiOff, Clock, Activity } from 'lucide-react';

const FuturesFooterStatus = memo(function FuturesFooterStatus() {
  const wsStatus = useMarketStore((s) => s.wsStatus);
  const activeSubscriptions = useUnifiedFuturesStore((s) => Object.keys(s.quotes).length);
  const lastUpdate = useUnifiedFuturesStore((s) => s._lastQuoteUpdate);

  const isConnected = wsStatus === 'connected';
  const isReconnecting = wsStatus === 'connecting';

  const statusColor = isConnected
    ? 'text-emerald-400'
    : isReconnecting
    ? 'text-amber-400'
    : 'text-red-400';

  const statusLabel = isConnected
    ? 'WS Connected'
    : isReconnecting
    ? 'Reconnecting...'
    : 'Disconnected';

  const StatusIcon = isConnected ? Wifi : WifiOff;

  const lastTickStr = lastUpdate
    ? new Date(lastUpdate).toLocaleTimeString('en-IN', {
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
      })
    : '--:--:--';

  return (
    <div className="flex items-center justify-between px-3 py-1 bg-gray-950 border-t border-gray-800 text-[10px] text-gray-500 select-none">
      <div className="flex items-center gap-3">
        <div className={cn('flex items-center gap-1', statusColor)}>
          <StatusIcon size={10} />
          <span>{statusLabel}</span>
        </div>
        <div className="flex items-center gap-1">
          <Clock size={10} />
          <span>Last tick: {lastTickStr}</span>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-1">
          <Activity size={10} />
          <span>{activeSubscriptions} streams</span>
        </div>
        <span className="text-gray-700">FUTURES V2</span>
      </div>
    </div>
  );
});

export default FuturesFooterStatus;
