"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { livePositions, liveTotal } from "@/lib/portfolio";
import type { ChatResponse, Portfolio, Snapshot, WatchlistEntry } from "@/lib/types";
import { usePriceStream } from "@/lib/usePriceStream";
import { ChatPanel } from "./ChatPanel";
import { Header } from "./Header";
import { Heatmap } from "./Heatmap";
import { MainChart } from "./MainChart";
import { PnlChart } from "./PnlChart";
import { PositionsTable } from "./PositionsTable";
import { TradeBar } from "./TradeBar";
import { Watchlist } from "./Watchlist";

const HISTORY_REFRESH_MS = 30_000;

export function Terminal() {
  const stream = usePriceStream();
  const [watchlist, setWatchlist] = useState<WatchlistEntry[]>([]);
  const [portfolio, setPortfolio] = useState<Portfolio | null>(null);
  const [snapshots, setSnapshots] = useState<Snapshot[]>([]);
  const [selected, setSelected] = useState<string | null>(null);

  const loadWatchlist = useCallback(() => api.watchlist().then((r) => setWatchlist(r.watchlist)), []);
  const loadPortfolio = useCallback(() => api.portfolio().then(setPortfolio), []);
  const loadHistory = useCallback(() => api.history().then((r) => setSnapshots(r.snapshots)), []);

  useEffect(() => {
    loadWatchlist();
    loadPortfolio();
    loadHistory();
    const timer = setInterval(loadHistory, HISTORY_REFRESH_MS);
    return () => clearInterval(timer);
  }, [loadWatchlist, loadPortfolio, loadHistory]);

  const active = selected && watchlist.some((w) => w.ticker === selected) ? selected : watchlist[0]?.ticker ?? null;

  const prices = useMemo(
    () => Object.fromEntries(Object.values(stream.prices).map((p) => [p.ticker, p.price])),
    [stream.prices],
  );
  const positions = useMemo(() => (portfolio ? livePositions(portfolio, prices) : []), [portfolio, prices]);
  const total = portfolio ? liveTotal(portfolio, prices) : null;

  const trade = async (ticker: string, quantity: number, side: "buy" | "sell") => {
    const result = await api.trade(ticker, quantity, side);
    setPortfolio(result.portfolio);
    loadHistory();
  };

  const add = async (ticker: string) => {
    await api.addTicker(ticker);
    await loadWatchlist();
    setSelected(ticker);
  };

  const remove = async (ticker: string) => {
    await api.removeTicker(ticker);
    await loadWatchlist();
  };

  const onChatActions = (reply: ChatResponse) => {
    if (reply.watchlist_changes.length) loadWatchlist();
    if (reply.trades.length) {
      loadPortfolio();
      loadHistory();
    }
  };

  return (
    <div className="flex h-screen flex-col">
      <Header total={total} cash={portfolio?.cash_balance ?? null} state={stream.state} />
      <div className="flex min-h-0 flex-1">
        <main className="grid min-h-0 min-w-0 flex-1 grid-cols-[minmax(260px,300px)_1fr] gap-1 p-1">
          <Watchlist entries={watchlist} prices={stream.prices} history={stream.history} selected={active}
            onSelect={setSelected} onAdd={add} onRemove={remove} />
          <div className="grid min-h-0 min-w-0 grid-rows-[minmax(200px,1.3fr)_minmax(160px,1fr)_minmax(120px,0.8fr)_auto] gap-1">
            <MainChart ticker={active} points={active ? stream.history[active] ?? [] : []} />
            <div className="grid min-h-0 grid-cols-2 gap-1">
              <Heatmap positions={positions} />
              <PnlChart snapshots={snapshots} />
            </div>
            <PositionsTable positions={positions} />
            <TradeBar ticker={active} onTrade={trade} />
          </div>
        </main>
        <ChatPanel onActions={onChatActions} />
      </div>
    </div>
  );
}
