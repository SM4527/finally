"use client";

import { useEffect, useRef, useState } from "react";
import { fmtPct, fmtPrice } from "@/lib/format";
import { changePercent } from "@/lib/portfolio";
import type { PricePoint } from "@/lib/types";
import { Sparkline } from "./Sparkline";

const FLASH_MS = 120;

/** Returns "flash-up"/"flash-down" briefly after the price changes. */
export function useFlash(price: number | undefined): string {
  const prev = useRef(price);
  const [flash, setFlash] = useState("");
  useEffect(() => {
    if (price === undefined || prev.current === undefined || price === prev.current) {
      prev.current = price;
      return;
    }
    setFlash(price > prev.current ? "flash-up" : "flash-down");
    prev.current = price;
    const t = setTimeout(() => setFlash(""), FLASH_MS);
    return () => clearTimeout(t);
  }, [price]);
  return flash;
}

export function WatchlistRow({ ticker, price, points, selected, onSelect, onRemove }: {
  ticker: string;
  price: number | undefined;
  points: PricePoint[];
  selected: boolean;
  onSelect: () => void;
  onRemove: () => void;
}) {
  const flash = useFlash(price);
  const change = price !== undefined && points.length ? changePercent(price, points[0].value) : null;
  return (
    <tr
      data-testid={`watchlist-row-${ticker}`}
      onClick={onSelect}
      className={`group cursor-pointer border-b border-line/60 ${selected ? "bg-raised" : "hover:bg-raised/60"}`}
    >
      <td className={`py-1.5 pl-3 font-semibold ${selected ? "text-accent" : ""}`}>{ticker}</td>
      <td data-testid={`watchlist-price-${ticker}`} className={`price-cell px-1 text-right ${flash}`}>
        {price === undefined ? "—" : fmtPrice(price)}
      </td>
      <td className={`px-1 text-right text-xs ${change === null ? "text-dim" : change >= 0 ? "text-up" : "text-down"}`}>
        {change === null ? "—" : fmtPct(change)}
      </td>
      <td className="px-1"><Sparkline points={points} width={64} height={20} /></td>
      <td className="pr-2 text-right">
        <button
          data-testid={`watchlist-remove-${ticker}`}
          aria-label={`Remove ${ticker}`}
          onClick={(e) => { e.stopPropagation(); onRemove(); }}
          className="px-1 text-dim opacity-0 hover:text-down focus:opacity-100 group-hover:opacity-100"
        >
          ×
        </button>
      </td>
    </tr>
  );
}
