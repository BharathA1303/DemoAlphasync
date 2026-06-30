import { cn } from '../../utils/cn';
import { useResponsive } from '../hooks/useResponsive';
import { VirtualizedTradingList } from '../hardening/VirtualizedTradingList';

/**
 * Options chain mobile wrapper — virtualization + sticky strike + horizontal scroll.
 * Desktop: renders children unchanged.
 */
export function HardenedOptionsChainShell({
  children,
  strikes = [],
  renderStrikeRow,
  className,
  header = null,
}) {
  const { isDesktop } = useResponsive();

  if (isDesktop) {
    return <div className={className}>{children}</div>;
  }

  if (strikes.length > 0 && renderStrikeRow) {
    return (
      <div className={cn('hard-options-chain flex flex-col min-h-0', className)}>
        {header}
        <VirtualizedTradingList
          items={strikes}
          rowHeight={40}
          className="flex-1 min-h-0"
          stickyHeader={
            header ? (
              <div className="hard-options-strike-sticky sticky top-0 z-10">{header}</div>
            ) : null
          }
          renderRow={renderStrikeRow}
        />
      </div>
    );
  }

  return (
    <div
      className={cn('hard-options-chain overflow-x-auto overscroll-x-contain', className)}
      data-scroll-region="x"
    >
      {children}
    </div>
  );
}

export default HardenedOptionsChainShell;
