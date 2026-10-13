import { useEffect, useRef, useState } from "react";

/** Observe an element's content width (ResizeObserver) for responsive SVG charts. */
export function useElementWidth<T extends HTMLElement>(fallback = 640) {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w && Math.abs(w - width) > 1) setWidth(Math.floor(w));
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [width]);
  return { ref, width };
}
