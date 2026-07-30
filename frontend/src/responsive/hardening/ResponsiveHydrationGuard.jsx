import { useLayoutEffect, useState } from 'react';

/**
 * Marks hydration complete without visibility:hidden (which breaks flex layouts until refresh).
 */
export function ResponsiveHydrationGuard({ children }) {
  const [ready, setReady] = useState(false);

  useLayoutEffect(() => {
    setReady(true);
  }, []);

  return (
    <div
      className="hard-hydration-root flex flex-col flex-1 min-h-0 min-w-0"
      data-hydration-ready={ready ? 'true' : 'false'}
    >
      {children}
    </div>
  );
}

export default ResponsiveHydrationGuard;
