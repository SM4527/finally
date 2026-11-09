"use client";

import { useState } from "react";
import type { PricePoint, PriceUpdate, WatchlistEntry } from "@/lib/types";
import { Panel } from "./Panel";
import { WatchlistRow } from "./WatchlistRow";

export function Watchlist({ entries, prices, history, selected, onSelect, onAdd, onRemove }: {
  entries: WatchlistEntry[];
  prices: Record<string, PriceUpdate>;
  history: Record<string, PricePoint[]>;
  selected: string | null;
  onSelect: (ticker: string) => void;
  onAdd: (ticker: string) => Promise<void>;
  onRemove: (ticker: string) => Promise<void>;
}) {
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);

  const add = async (e: React.FormEvent) => {
    e.preventDefault();
    const ticker = input.trim().toUpperCase();
    if (!ticker) return;
    try {
      await onAdd(ticker);
      setInput("");
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <Panel title="Watchlist" className="h-full">
      <div className="flex h-full flex-col">
        <form onSubmit={add} className="flex gap-1 border-b border-line p-2">
          <input
            data-testid="watchlist-add-input"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Add ticker"
            aria-label="Ticker to add"
            className="min-w-0 flex-1 border border-line bg-ink px-2 py-1 text-sm uppercase placeholder:normal-case placeholder:text-dim"
          />
          <button data-testid="watchlist-add-button" type="submit" className="bg-blue px-3 text-sm font-semibold text-ink hover:brightness-110">
            Add
          </button>
        </form>
        {error && <p className="px-3 py-1 text-xs text-down">{error}</p>}
        <div className="min-h-0 flex-1 overflow-y-auto">
          <table className="w-full text-sm">
            <tbody>
              {entries.map((e) => (
                <WatchlistRow
                  key={e.ticker}
                  ticker={e.ticker}
                  price={prices[e.ticker]?.price ?? e.price ?? undefined}
                  points={history[e.ticker] ?? []}
                  selected={selected === e.ticker}
                  onSelect={() => onSelect(e.ticker)}
                  onRemove={() => onRemove(e.ticker).catch((err) => setError(err.message))}
                />
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </Panel>
  );
}
