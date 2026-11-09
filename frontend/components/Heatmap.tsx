import { fmtPct } from "@/lib/format";
import type { LivePosition } from "@/lib/portfolio";
import { squarify } from "@/lib/treemap";
import { Panel } from "./Panel";

/** Tile background: stronger green/red as P&L % grows, saturating at 5%. */
export function tileColor(pnlPercent: number): string {
  const strength = Math.round(20 + Math.min(Math.abs(pnlPercent) / 5, 1) * 60);
  const hue = pnlPercent >= 0 ? "var(--color-up)" : "var(--color-down)";
  return `color-mix(in srgb, ${hue} ${strength}%, var(--color-raised))`;
}

export function Heatmap({ positions }: { positions: LivePosition[] }) {
  const tiles = squarify(positions, (p) => p.market_value, { x: 0, y: 0, w: 100, h: 100 });
  return (
    <Panel title="Positions heatmap" className="h-full">
      <div data-testid="heatmap" className="relative h-full w-full">
        {tiles.length === 0 && (
          <p className="absolute inset-0 grid place-items-center text-sm text-dim">Buy a stock to see your allocation</p>
        )}
        {tiles.map(({ item, x, y, w, h }) => (
          <div
            key={item.ticker}
            data-testid={`heatmap-tile-${item.ticker}`}
            data-pnl={item.unrealized_pnl >= 0 ? "up" : "down"}
            title={`${item.ticker} ${(item.weight * 100).toFixed(1)}% of positions`}
            className="absolute flex flex-col items-center justify-center overflow-hidden border border-ink text-xs"
            style={{ left: `${x}%`, top: `${y}%`, width: `${w}%`, height: `${h}%`, background: tileColor(item.unrealized_pnl_percent) }}
          >
            <span className="font-bold">{item.ticker}</span>
            <span>{fmtPct(item.unrealized_pnl_percent)}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}
