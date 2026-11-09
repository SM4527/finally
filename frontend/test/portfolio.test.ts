import { changePercent, livePositions, liveTotal } from "@/lib/portfolio";
import { squarify } from "@/lib/treemap";
import { appendTicks } from "@/lib/usePriceStream";
import { snapshotPoints } from "@/components/PnlChart";
import type { Portfolio } from "@/lib/types";

const portfolio: Portfolio = {
  cash_balance: 8000,
  positions_value: 2000,
  total_value: 10000,
  unrealized_pnl: 0,
  positions: [
    { ticker: "AAPL", quantity: 10, avg_cost: 100, current_price: 100, market_value: 1000, unrealized_pnl: 0, unrealized_pnl_percent: 0 },
    { ticker: "MSFT", quantity: 2, avg_cost: 500, current_price: 500, market_value: 1000, unrealized_pnl: 0, unrealized_pnl_percent: 0 },
  ],
};

describe("portfolio calculations", () => {
  it("revalues positions with live prices", () => {
    const [aapl, msft] = livePositions(portfolio, { AAPL: 110 });
    expect(aapl.market_value).toBe(1100);
    expect(aapl.unrealized_pnl).toBe(100);
    expect(aapl.unrealized_pnl_percent).toBeCloseTo(10);
    expect(msft.current_price).toBe(500);
    expect(aapl.weight + msft.weight).toBeCloseTo(1);
  });

  it("computes the live total as cash plus market value", () => {
    expect(liveTotal(portfolio, { AAPL: 90, MSFT: 510 })).toBe(8000 + 900 + 1020);
  });

  it("computes change percent", () => {
    expect(changePercent(105, 100)).toBeCloseTo(5);
    expect(changePercent(5, 0)).toBe(0);
  });
});

describe("treemap", () => {
  it("fills the rect with tiles proportional to value", () => {
    const tiles = squarify([3, 2, 1], (v) => v, { x: 0, y: 0, w: 100, h: 100 });
    const area = tiles.reduce((s, t) => s + t.w * t.h, 0);
    expect(area).toBeCloseTo(10000);
    expect(tiles[0].w * tiles[0].h).toBeCloseTo(5000);
  });
});

describe("price buffer", () => {
  it("appends ticks and skips non-increasing timestamps", () => {
    const tick = (price: number, timestamp: number) => ({ AAPL: { ticker: "AAPL", price, previous_price: 0, timestamp } });
    let h = appendTicks({}, tick(1, 10));
    h = appendTicks(h, tick(2, 11));
    h = appendTicks(h, tick(3, 11));
    expect(h.AAPL).toEqual([{ time: 10, value: 1 }, { time: 11, value: 2 }]);
  });

  it("dedupes snapshots in the same second", () => {
    const pts = snapshotPoints([
      { total_value: 1, recorded_at: "2026-10-24T14:00:00Z" },
      { total_value: 2, recorded_at: "2026-10-24T14:00:00Z" },
      { total_value: 3, recorded_at: "2026-10-24T14:00:30Z" },
    ]);
    expect(pts.map((p) => p.value)).toEqual([2, 3]);
  });
});
