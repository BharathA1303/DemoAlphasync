import { useEffect, useState } from 'react';
import { getViewportChecklist } from '../utils/testing';

/**
 * Dev-only responsive QA overlay.
 */
export function ResponsiveViewportDebugger() {
  const [visible, setVisible] = useState(false);
  const [dims, setDims] = useState({ w: 0, h: 0 });

  useEffect(() => {
    if (!import.meta.env?.DEV) return;
    const update = () =>
      setDims({
        w: window.innerWidth,
        h: window.visualViewport?.height ?? window.innerHeight,
      });
    update();
    window.addEventListener('resize', update, { passive: true });
    return () => window.removeEventListener('resize', update);
  }, []);

  if (!import.meta.env?.DEV) return null;

  const checklist = getViewportChecklist();
  const match = checklist.find((c) => Math.abs(c.width - dims.w) < 24);

  return (
    <>
      <button
        type="button"
        className="hard-viewport-debug-toggle"
        onClick={() => setVisible((v) => !v)}
        aria-label="Toggle responsive debugger"
      >
        R
      </button>
      {visible && (
        <div className="hard-viewport-debug-panel" role="complementary">
          <div className="font-semibold text-heading text-xs mb-1">Responsive QA</div>
          <div className="text-[10px] text-gray-500 tabular-nums">
            {dims.w}×{dims.h}px
            {match ? ` · preset ~${match.width}` : ''}
          </div>
          <ul className="mt-2 space-y-0.5 text-[10px] text-gray-500">
            {(match?.checks ?? checklist[0]?.checks ?? []).slice(0, 5).map((c) => (
              <li key={c}>□ {c}</li>
            ))}
          </ul>
        </div>
      )}
    </>
  );
}

export default ResponsiveViewportDebugger;
