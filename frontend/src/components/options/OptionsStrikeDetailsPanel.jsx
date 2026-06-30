import { memo } from 'react';
import { cn } from '../../utils/cn';
import {
  formatZebuOi,
  formatZebuPct,
  formatZebuPrice,
  isZebuChainSource,
  oiChangePercent,
} from './formatZebuValue';
import { computeLiquidityLabel } from '../../utils/optionsAnalytics';

function DetailRow({ label, value, valueClassName, hint }) {
  return (
    <div className="flex items-center justify-between gap-2 py-1 min-h-[24px] border-b border-edge/[0.04] last:border-0">
      <span className="text-[10px] options-chain-label uppercase tracking-wide">{label}</span>
      <div className="text-right min-w-0">
        <span
          className={cn(
            'text-[11px] font-mono font-semibold tabular-nums text-heading block',
            valueClassName,
          )}
        >
          {value}
        </span>
        {hint && <span className="text-[9px] options-chain-muted block">{hint}</span>}
      </div>
    </div>
  );
}

function OptionsStrikeDetailsPanel({
  underlying,
  expiry,
  strike,
  optionType,
  sideData,
  oppositeSideData,
  source,
  displaySymbol,
}) {
  const zebu = isZebuChainSource(source);

  if (!strike) {
    return (
      <div className="p-4 text-center text-xs options-chain-muted">
        Select a strike from the chain
      </div>
    );
  }

  const oiPct = sideData ? oiChangePercent(sideData.oi, sideData.oiChange) : null;
  const spread =
    sideData?.ask != null && sideData?.bid != null && Number(sideData.ask) > 0
      ? Number(sideData.ask) - Number(sideData.bid)
      : null;
  const liquidity = computeLiquidityLabel(sideData);
  const waiting = zebu ? null : 'Waiting for live quote';

  return (
    <div className="flex flex-col h-full min-h-0 overflow-y-auto">
      <div className="px-3 py-2 border-b border-edge/10 flex-shrink-0">
        <div className="text-[10px] font-semibold uppercase tracking-wider options-chain-label mb-1">
          Selected Strike · Live
        </div>
        <div
          className={cn(
            'text-sm font-bold truncate',
            optionType === 'CE' ? 'text-emerald-600 dark:text-emerald-400' : 'text-red-600 dark:text-red-400',
          )}
        >
          {displaySymbol}
        </div>
        <div className="text-[10px] options-chain-muted mt-0.5">
          {underlying} · {expiry || '—'} · {optionType}
          {sideData?.tsym ? ` · ${sideData.tsym}` : ''}
        </div>
      </div>

      <div className="px-3 py-2 flex-1">
        {!zebu && (
          <p className="text-xs text-amber-600 dark:text-amber-400 mb-3">
            Waiting for Zebu live quotes
          </p>
        )}

        <DetailRow
          label="Liquidity"
          value={liquidity.label}
          valueClassName={
            liquidity.tone === 'good'
              ? 'text-bull'
              : liquidity.tone === 'warn'
                ? 'text-bear'
                : undefined
          }
          hint="From bid-ask vs mid (Zebu)"
        />
        <DetailRow
          label="LTP"
          value={formatZebuPrice(sideData?.ltp, { source, bid: sideData?.bid, ask: sideData?.ask })}
          hint={waiting}
        />
        <DetailRow
          label="Change"
          value={formatZebuPct(sideData?.changePct, { source })}
          valueClassName={Number(sideData?.changePct) >= 0 ? 'text-bull' : 'text-bear'}
        />
        <DetailRow label="Bid" value={formatZebuPrice(sideData?.bid, { source })} />
        <DetailRow label="Ask" value={formatZebuPrice(sideData?.ask, { source })} />
        <DetailRow
          label="Spread"
          value={spread != null && zebu ? `₹${spread.toFixed(2)}` : '—'}
        />
        <DetailRow label="OI" value={formatZebuOi(sideData?.oi, { source })} />
        <DetailRow
          label="OI Change"
          value={oiPct != null ? formatZebuPct(oiPct, { source }) : '—'}
          valueClassName={oiPct != null && oiPct >= 0 ? 'text-bull' : 'text-bear'}
        />
        <DetailRow label="Volume" value={formatZebuOi(sideData?.volume, { source })} />

        {oppositeSideData && (
          <>
            <div className="text-[10px] font-semibold uppercase options-chain-label mt-3 mb-1">
              Opposite ({optionType === 'CE' ? 'PE' : 'CE'})
            </div>
            <DetailRow label="LTP" value={formatZebuPrice(oppositeSideData?.ltp, { source })} />
            <DetailRow label="OI" value={formatZebuOi(oppositeSideData?.oi, { source })} />
            <DetailRow label="Volume" value={formatZebuOi(oppositeSideData?.volume, { source })} />
          </>
        )}
      </div>
    </div>
  );
}

export default memo(OptionsStrikeDetailsPanel);
