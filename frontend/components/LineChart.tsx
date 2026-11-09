"use client";

import { AreaSeries, ColorType, createChart, type IChartApi, type ISeriesApi, type UTCTimestamp } from "lightweight-charts";
import { useEffect, useRef } from "react";
import type { PricePoint } from "@/lib/types";

/** Area chart over (unix seconds, value) points using Lightweight Charts. */
export function LineChart({ points, color, testId }: { points: PricePoint[]; color: string; testId: string }) {
  const el = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const series = useRef<ISeriesApi<"Area"> | null>(null);

  useEffect(() => {
    const c = createChart(el.current!, {
      autoSize: true,
      layout: { background: { type: ColorType.Solid, color: "transparent" }, textColor: "#7b8794", attributionLogo: false },
      grid: { vertLines: { color: "#1c2532" }, horzLines: { color: "#1c2532" } },
      rightPriceScale: { borderColor: "#253040" },
      timeScale: { borderColor: "#253040", timeVisible: true, secondsVisible: true },
      crosshair: { horzLine: { color: "#7b8794" }, vertLine: { color: "#7b8794" } },
    });
    chart.current = c;
    series.current = c.addSeries(AreaSeries, {
      lineColor: color,
      lineWidth: 2,
      topColor: `${color}55`,
      bottomColor: `${color}00`,
      priceLineVisible: false,
    });
    return () => c.remove();
  }, [color]);

  useEffect(() => {
    series.current?.setData(points.map((p) => ({ time: p.time as UTCTimestamp, value: p.value })));
    chart.current?.timeScale().fitContent();
  }, [points, color]);

  return <div ref={el} data-testid={testId} data-points={points.length} className="h-full w-full" />;
}
