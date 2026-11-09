import { fmtPct, fmtPrice, fmtQty, fmtSigned } from "@/lib/format";
import type { LivePosition } from "@/lib/portfolio";
import { Panel } from "./Panel";

const tone = (v: number) => (v >= 0 ? "text-up" : "text-down");

export function PositionsTable({ positions }: { positions: LivePosition[] }) {
  return (
    <Panel title="Positions" className="h-full">
      <div className="h-full overflow-auto">
        <table data-testid="positions-table" className="w-full text-sm">
          <thead className="sticky top-0 bg-panel text-xs text-dim">
            <tr className="text-right">
              <th className="py-1 pl-3 text-left font-medium">Ticker</th>
              <th className="font-medium">Qty</th>
              <th className="font-medium">Avg cost</th>
              <th className="font-medium">Price</th>
              <th className="font-medium">P&amp;L</th>
              <th className="pr-3 font-medium">P&amp;L %</th>
            </tr>
          </thead>
          <tbody>
            {positions.map((p) => (
              <tr key={p.ticker} data-testid={`position-row-${p.ticker}`} className="border-t border-line/60 text-right">
                <td className="py-1 pl-3 text-left font-semibold">{p.ticker}</td>
                <td>{fmtQty(p.quantity)}</td>
                <td>{fmtPrice(p.avg_cost)}</td>
                <td>{fmtPrice(p.current_price)}</td>
                <td className={tone(p.unrealized_pnl)}>{fmtSigned(p.unrealized_pnl)}</td>
                <td className={`pr-3 ${tone(p.unrealized_pnl)}`}>{fmtPct(p.unrealized_pnl_percent)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {positions.length === 0 && <p className="px-3 py-3 text-sm text-dim">No positions yet. Use the trade bar or ask the assistant.</p>}
      </div>
    </Panel>
  );
}
