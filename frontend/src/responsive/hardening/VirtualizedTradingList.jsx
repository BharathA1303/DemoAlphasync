import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { cn } from '../../utils/cn';

/**
 * Lightweight virtualized list for orders / positions / option strikes on mobile.
 */
export function VirtualizedTradingList({
  items = [],
  rowHeight = 44,
  overscan = 6,
  renderRow,
  className,
  emptyMessage = 'No rows',
  onRowClick,
  stickyHeader = null,
}) {
  const containerRef = useRef(null);
  const [scrollTop, setScrollTop] = useState(0);
  const [viewportH, setViewportH] = useState(320);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setViewportH(el.clientHeight || 320));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const onScroll = useCallback((e) => {
    setScrollTop(e.currentTarget.scrollTop);
  }, []);

  const { start, end, totalHeight, offsetY } = useMemo(() => {
    const count = items.length;
    const startIdx = Math.max(0, Math.floor(scrollTop / rowHeight) - overscan);
    const visible = Math.ceil(viewportH / rowHeight) + overscan * 2;
    const endIdx = Math.min(count, startIdx + visible);
    return {
      start: startIdx,
      end: endIdx,
      totalHeight: count * rowHeight,
      offsetY: startIdx * rowHeight,
    };
  }, [items.length, scrollTop, rowHeight, viewportH, overscan]);

  const slice = items.slice(start, end);

  return (
    <div
      ref={containerRef}
      className={cn('hard-virtual-list overflow-y-auto overscroll-contain', className)}
      data-scroll-region="y"
      onScroll={onScroll}
      role="list"
    >
      {stickyHeader}
      {items.length === 0 ? (
        <div className="py-8 text-center text-xs text-gray-500">{emptyMessage}</div>
      ) : (
        <div style={{ height: totalHeight, position: 'relative' }}>
          <div
            style={{
              transform: `translateY(${offsetY}px)`,
              willChange: 'transform',
            }}
          >
            {slice.map((item, i) => {
              const index = start + i;
              return (
                <div
                  key={item.id ?? item.key ?? index}
                  role="listitem"
                  style={{ height: rowHeight }}
                  className="hard-virtual-row flex items-center border-b border-edge/5"
                  onClick={onRowClick ? () => onRowClick(item, index) : undefined}
                >
                  {renderRow(item, index)}
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

export default VirtualizedTradingList;
