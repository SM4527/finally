import { fmtPrice, fmtQty } from "@/lib/format";
import type { ChatActions as Actions, TradeResult, WatchlistChangeResult } from "@/lib/types";

function ActionLine({ ok, text, error }: { ok: boolean; text: string; error: string | null }) {
  return (
    <li data-testid="chat-action" data-status={ok ? "ok" : "error"}
      className={`border-l-2 pl-2 text-xs ${ok ? "border-up text-up" : "border-down text-down"}`}>
      {text}{error && <span className="text-dim">: {error}</span>}
    </li>
  );
}

export function watchlistText(w: WatchlistChangeResult): string {
  const verb = w.action === "add" ? `add ${w.ticker} to` : `remove ${w.ticker} from`;
  if (w.status === "ok") return w.action === "add" ? `Added ${w.ticker} to watchlist` : `Removed ${w.ticker} from watchlist`;
  return `Failed to ${verb} watchlist`;
}

export function tradeText(t: TradeResult): string {
  if (t.status === "ok") return `${t.side === "buy" ? "Bought" : "Sold"} ${fmtQty(t.quantity)} ${t.ticker} at $${fmtPrice(t.price ?? 0)}`;
  return `Failed to ${t.side} ${fmtQty(t.quantity)} ${t.ticker}`;
}

export function ChatActions({ actions }: { actions: Actions | null }) {
  if (!actions || (!actions.watchlist_changes.length && !actions.trades.length)) return null;
  return (
    <ul className="mt-2 space-y-1">
      {actions.watchlist_changes.map((w, i) => (
        <ActionLine key={`w${i}`} ok={w.status === "ok"} error={w.error} text={watchlistText(w)} />
      ))}
      {actions.trades.map((t, i) => (
        <ActionLine key={`t${i}`} ok={t.status === "ok"} error={t.error} text={tradeText(t)} />
      ))}
    </ul>
  );
}
