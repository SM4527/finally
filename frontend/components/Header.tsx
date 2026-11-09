import { fmtMoney } from "@/lib/format";
import type { ConnectionState } from "@/lib/types";

const DOT: Record<ConnectionState, { color: string; label: string }> = {
  open: { color: "bg-up", label: "Live" },
  connecting: { color: "bg-accent", label: "Reconnecting" },
  closed: { color: "bg-down", label: "Disconnected" },
};

export function Header({ total, cash, state }: { total: number | null; cash: number | null; state: ConnectionState }) {
  const dot = DOT[state];
  return (
    <header className="flex items-end justify-between gap-6 border-b border-line px-4 pb-2 pt-3">
      <div className="flex items-baseline gap-3">
        <h1 className="text-2xl font-black tracking-tight text-accent [font-stretch:75%]">FinAlly</h1>
        <span className="text-xs text-dim">AI trading workstation</span>
      </div>
      <div className="flex items-end gap-8">
        <div className="text-right">
          <div className="text-[11px] text-dim">Portfolio value</div>
          <div data-testid="header-total" className="text-3xl font-bold leading-none [font-stretch:80%]">
            {total === null ? "—" : fmtMoney(total)}
          </div>
        </div>
        <div className="text-right">
          <div className="text-[11px] text-dim">Cash</div>
          <div data-testid="header-cash" className="text-lg font-semibold leading-none">
            {cash === null ? "—" : fmtMoney(cash)}
          </div>
        </div>
        <div className="flex items-center gap-2 pb-0.5 text-xs text-dim" title={dot.label}>
          <span data-testid="connection-dot" data-state={state} className={`h-2.5 w-2.5 rounded-full ${dot.color}`} />
          {dot.label}
        </div>
      </div>
    </header>
  );
}
