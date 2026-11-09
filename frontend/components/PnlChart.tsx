"use client";

import { useMemo } from "react";
import type { PricePoint, Snapshot } from "@/lib/types";
import { LineChart } from "./LineChart";
import { Panel } from "./Panel";

/** Snapshots to strictly increasing chart points (last value wins per second). */
export function snapshotPoints(snapshots: Snapshot[]): PricePoint[] {
  const points: PricePoint[] = [];
  for (const s of snapshots) {
    const time = Math.floor(Date.parse(s.recorded_at) / 1000);
    const last = points[points.length - 1];
    if (last && time <= last.time) last.value = s.total_value;
    else points.push({ time, value: s.total_value });
  }
  return points;
}

export function PnlChart({ snapshots }: { snapshots: Snapshot[] }) {
  const points = useMemo(() => snapshotPoints(snapshots), [snapshots]);
  return (
    <Panel title="Portfolio value" className="h-full">
      <div className="h-full p-1">
        <LineChart points={points} color="#ecad0a" testId="pnl-chart" />
      </div>
    </Panel>
  );
}
