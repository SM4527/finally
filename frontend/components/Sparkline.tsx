import type { PricePoint } from "@/lib/types";

export function Sparkline({ points, width = 80, height = 24 }: { points: PricePoint[]; width?: number; height?: number }) {
  if (points.length < 2) return <svg width={width} height={height} aria-hidden />;
  const values = points.map((p) => p.value);
  const min = Math.min(...values);
  const range = Math.max(...values) - min || 1;
  const step = width / (points.length - 1);
  const path = values.map((v, i) => `${(i * step).toFixed(1)},${(height - ((v - min) / range) * (height - 2) - 1).toFixed(1)}`).join(" ");
  const up = values[values.length - 1] >= values[0];
  return (
    <svg width={width} height={height} aria-hidden>
      <polyline points={path} fill="none" strokeWidth={1.25} className={up ? "stroke-up" : "stroke-down"} />
    </svg>
  );
}
