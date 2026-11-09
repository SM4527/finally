"use client";

import { useEffect, useState } from "react";

export function TradeBar({ ticker: selected, onTrade }: {
  ticker: string | null;
  onTrade: (ticker: string, quantity: number, side: "buy" | "sell") => Promise<void>;
}) {
  const [ticker, setTicker] = useState(selected ?? "");
  const [quantity, setQuantity] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (selected) setTicker(selected); }, [selected]);

  const submit = async (side: "buy" | "sell") => {
    const qty = Number(quantity);
    if (!ticker.trim()) return setError("Enter a ticker");
    if (!(qty > 0)) return setError("Enter a quantity greater than 0");
    setBusy(true);
    try {
      await onTrade(ticker.trim().toUpperCase(), qty, side);
      setError(null);
      setQuantity("");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const field = "border border-line bg-ink px-2 py-1.5 text-sm";
  return (
    <form onSubmit={(e) => { e.preventDefault(); submit("buy"); }} className="flex flex-wrap items-center gap-2 border border-line bg-panel px-3 py-2">
      <span className="text-[13px] font-semibold text-dim [font-stretch:85%]">Market order</span>
      <input data-testid="trade-ticker" aria-label="Ticker" value={ticker} onChange={(e) => setTicker(e.target.value)}
        placeholder="Ticker" className={`${field} w-24 uppercase placeholder:normal-case placeholder:text-dim`} />
      <input data-testid="trade-quantity" aria-label="Quantity" value={quantity} onChange={(e) => setQuantity(e.target.value)}
        placeholder="Qty" inputMode="decimal" className={`${field} w-24 placeholder:text-dim`} />
      <button data-testid="trade-buy" type="submit" disabled={busy}
        className="bg-up px-4 py-1.5 text-sm font-bold text-ink hover:brightness-110 disabled:opacity-50">Buy</button>
      <button data-testid="trade-sell" type="button" disabled={busy} onClick={() => submit("sell")}
        className="bg-down px-4 py-1.5 text-sm font-bold text-ink hover:brightness-110 disabled:opacity-50">Sell</button>
      {error && <span data-testid="trade-error" role="alert" className="text-sm text-down">{error}</span>}
    </form>
  );
}
