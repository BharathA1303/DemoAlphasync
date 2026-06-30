/**
 * Dev-only interaction profiler (frame budget warnings).
 */

let raf = null;
let cleanup = null;

export function initResponsiveInteractionProfiler() {
  if (!import.meta.env?.DEV || typeof window === 'undefined') return;

  let last = performance.now();
  let frames = 0;
  let slow = 0;

  const loop = (now) => {
    const dt = now - last;
    last = now;
    frames += 1;
    if (dt > 32) slow += 1;
    if (frames % 120 === 0 && slow > 8) {
      console.debug('[ResponsiveInteractionProfiler] slow frames:', slow, '/120');
      slow = 0;
    }
    raf = requestAnimationFrame(loop);
  };

  raf = requestAnimationFrame(loop);
  cleanup = () => {
    if (raf) cancelAnimationFrame(raf);
    raf = null;
  };
}

export function disposeResponsiveInteractionProfiler() {
  cleanup?.();
  cleanup = null;
}
