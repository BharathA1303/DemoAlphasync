import { memo, useState } from 'react';
import { cn } from '../../utils/cn';
import Badge from '../ui/Badge';
import { formatCurrency, formatPrice, pnlColorClass } from '../../utils/formatters';

const TABS = [
  { key: 'positions', label: 'Positions' },
  { key: 'orders', label: 'Orders' },
  { key: 'legs', label: 'Strategy Legs' },
  { key: 'greeks', label: 'Greeks Exposure' },
  { key: 'history', label: 'Trade History' },
];

function OptionsBottomDock({
  collapsed,
  onToggleCollapse,
  positions,
  orders,
  onClosePosition,
}) {
  const [activeTab, setActiveTab] = useState('positions');

  return (
    <div className="h-full flex flex-col bg-surface-900 min-h-0">
      <div className="flex border-b border-edge/5 flex-shrink-0 items-center min-w-0">
        <button
          type="button"
          onClick={onToggleCollapse}
          className="px-2 py-2 text-gray-500 hover:text-heading flex-shrink-0"
        >
          <svg
            className={cn('w-3.5 h-3.5 transition-transform', collapsed ? '' : 'rotate-180')}
            viewBox="0 0 20 20"
            fill="currentColor"
          >
            <path
              fillRule="evenodd"
              d="M5.23 7.21a.75.75 0 011.06.02L10 11.168l3.71-3.938a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z"
              clipRule="evenodd"
            />
          </svg>
        </button>
        {TABS.map(({ key, label }) => {
          const count =
            key === 'positions' ? positions.length : key === 'orders' ? orders.length : 0;
          return (
            <button
              key={key}
              type="button"
              onClick={() => setActiveTab(key)}
              className={cn(
                'px-3 py-2 text-[10px] font-semibold uppercase tracking-wider whitespace-nowrap transition-colors',
                activeTab === key
                  ? 'text-primary-600 border-b-2 border-primary-500'
                  : 'text-gray-500 hover:text-gray-700',
              )}
            >
              {label}
              {count > 0 && key !== 'history' && key !== 'legs' && key !== 'greeks' ? ` (${count})` : ''}
            </button>
          );
        })}
      </div>

      {!collapsed && (
        <div className="overflow-y-auto flex-1 min-h-0 px-3 py-2">
          {activeTab === 'positions' &&
            (positions.length > 0 ? (
              <table className="w-full text-xs min-w-[640px]">
                <thead>
                  <tr className="text-gray-500 uppercase">
                    <th className="text-left pb-2 font-medium">Symbol</th>
                    <th className="text-right pb-2 font-medium">Side</th>
                    <th className="text-right pb-2 font-medium">Lots</th>
                    <th className="text-right pb-2 font-medium">Avg</th>
                    <th className="text-right pb-2 font-medium">LTP</th>
                    <th className="text-right pb-2 font-medium">P&L</th>
                    <th className="text-right pb-2 font-medium" />
                  </tr>
                </thead>
                <tbody>
                  {positions.map((pos) => (
                    <tr key={pos.id} className="border-t border-edge/[0.03] hover:bg-overlay/[0.02]">
                      <td className="py-1.5 font-medium text-heading">{pos.symbol}</td>
                      <td className="py-1.5 text-right">
                        <Badge variant={pos.side === 'BUY' ? 'bull' : 'bear'}>{pos.side}</Badge>
                      </td>
                      <td className="py-1.5 text-right font-mono text-gray-500">{pos.lots}</td>
                      <td className="py-1.5 text-right font-mono">₹{formatPrice(pos.avgPremium)}</td>
                      <td className="py-1.5 text-right font-mono">₹{formatPrice(pos.ltp)}</td>
                      <td className={cn('py-1.5 text-right font-mono font-semibold', pnlColorClass(pos.pnl))}>
                        {pos.pnl >= 0 ? '+' : ''}
                        {formatCurrency(pos.pnl)}
                      </td>
                      <td className="py-1.5 text-right">
                        <button
                          type="button"
                          onClick={() => onClosePosition(pos.id)}
                          className="text-[10px] px-2 py-0.5 rounded border border-edge/20 text-gray-500 hover:text-heading"
                        >
                          Close
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="text-center py-6 text-gray-600 text-xs">No open option positions.</div>
            ))}

          {activeTab === 'orders' &&
            (orders.length > 0 ? (
              <table className="w-full text-xs min-w-[640px]">
                <thead>
                  <tr className="text-gray-500 uppercase">
                    <th className="text-left pb-2">Time</th>
                    <th className="text-left pb-2">Symbol</th>
                    <th className="text-right pb-2">B/S</th>
                    <th className="text-right pb-2">Lots</th>
                    <th className="text-right pb-2">Premium</th>
                    <th className="text-right pb-2">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {orders.map((order) => (
                    <tr key={order.id} className="border-t border-edge/[0.03]">
                      <td className="py-1.5 text-gray-500">
                        {new Date(order.time || order.timestamp).toLocaleTimeString('en-IN', {
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                      </td>
                      <td className="py-1.5 text-heading">{order.symbol}</td>
                      <td className="py-1.5 text-right">
                        <Badge variant={order.side === 'BUY' ? 'bull' : 'bear'}>{order.side}</Badge>
                      </td>
                      <td className="py-1.5 text-right font-mono">{order.lots}</td>
                      <td className="py-1.5 text-right font-mono">₹{formatPrice(order.premium)}</td>
                      <td className="py-1.5 text-right text-[10px]">{order.status}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="text-center py-6 text-gray-600 text-xs">No option orders yet.</div>
            ))}

          {['legs', 'greeks', 'history'].includes(activeTab) && (
            <div className="text-center py-8 text-gray-600 text-xs">
              {activeTab === 'legs' && 'Strategy legs — link multi-leg orders here.'}
              {activeTab === 'greeks' && 'Portfolio Greeks exposure — available when positions are open.'}
              {activeTab === 'history' && 'Trade history syncs with executed paper orders.'}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export default memo(OptionsBottomDock);
