"use client";

import { fmtPct, fmtPrice } from "@/lib/format";
import { changePercent } from "@/lib/portfolio";
import type { PricePoint } from "@/lib/types";
import { LineChart } from "./LineChart";
import { Panel } from "./Panel";

export function MainChart({ ticker, points }: { ticker: string | null; points: PricePoint[] }) {
  const last = points[points.length - 1]?.value;
  const change = last !== undefined ? changePercent(last, points[0].value) : null;
  const aside = ticker && last !== undefined && change !== null && (
    <span className="text-sm">
      <span className="font-semibold">{fmtPrice(last)}</span>{" "}
      <span className={change >= 0 ? "text-up" : "text-down"}>{fmtPct(change)}</span>
      <span className="text-dim"> since load</span>
    </span>
  );
  return (
    <Panel title={ticker ?? "Select a ticker"} aside={aside} className="h-full">
      <div className="h-full p-1">
        <LineChart points={points} color="#209dd7" testId="main-chart" />
      </div>
    </Panel>
  );
}
