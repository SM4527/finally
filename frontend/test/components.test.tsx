import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Header } from "@/components/Header";
import { Heatmap } from "@/components/Heatmap";
import { PositionsTable } from "@/components/PositionsTable";
import { TradeBar } from "@/components/TradeBar";
import { Watchlist } from "@/components/Watchlist";
import { api } from "@/lib/api";
import { livePositions } from "@/lib/portfolio";
import type { Portfolio, PriceUpdate } from "@/lib/types";

const portfolio: Portfolio = {
  cash_balance: 8095,
  positions_value: 1955.3,
  total_value: 10050.3,
  unrealized_pnl: 50.3,
  positions: [
    { ticker: "AAPL", quantity: 10, avg_cost: 190.5, current_price: 195.53, market_value: 1955.3, unrealized_pnl: 50.3, unrealized_pnl_percent: 2.64 },
    { ticker: "TSLA", quantity: 1, avg_cost: 300, current_price: 270, market_value: 270, unrealized_pnl: -30, unrealized_pnl_percent: -10 },
  ],
};

const price = (ticker: string, p: number, t = 1): Record<string, PriceUpdate> => ({
  [ticker]: { ticker, price: p, previous_price: p, timestamp: t },
});

describe("Header", () => {
  it("shows total, cash and connection state", () => {
    render(<Header total={10050.3} cash={8095} state="open" />);
    expect(screen.getByTestId("header-total")).toHaveTextContent("$10,050.30");
    expect(screen.getByTestId("header-cash")).toHaveTextContent("$8,095.00");
    expect(screen.getByTestId("connection-dot")).toHaveAttribute("data-state", "open");
  });
});

describe("Positions", () => {
  it("renders a row per position with live P&L", () => {
    render(<PositionsTable positions={livePositions(portfolio, { AAPL: 200.5 })} />);
    const row = screen.getByTestId("position-row-AAPL");
    expect(row).toHaveTextContent("200.50");
    expect(row).toHaveTextContent("+$100.00");
    expect(row).toHaveTextContent("+5.25%");
  });

  it("colours heatmap tiles by P&L", () => {
    render(<Heatmap positions={livePositions(portfolio, {})} />);
    expect(screen.getByTestId("heatmap-tile-AAPL")).toHaveAttribute("data-pnl", "up");
    expect(screen.getByTestId("heatmap-tile-TSLA")).toHaveAttribute("data-pnl", "down");
  });
});

describe("Watchlist", () => {
  const props = {
    entries: [{ ticker: "AAPL", price: null, added_at: "" }],
    history: {},
    selected: null,
    onSelect: () => {},
    onAdd: vi.fn(async () => {}),
    onRemove: vi.fn(async () => {}),
  };

  it("shows a dash before the first price", () => {
    render(<Watchlist {...props} prices={{}} />);
    expect(screen.getByTestId("watchlist-price-AAPL")).toHaveTextContent("—");
  });

  it("flashes green on an uptick and red on a downtick", () => {
    vi.useFakeTimers();
    const { rerender } = render(<Watchlist {...props} prices={price("AAPL", 100)} />);
    const cell = screen.getByTestId("watchlist-price-AAPL");
    expect(cell).not.toHaveClass("flash-up");
    rerender(<Watchlist {...props} prices={price("AAPL", 101)} />);
    expect(cell).toHaveClass("flash-up");
    act(() => vi.advanceTimersByTime(200));
    expect(cell).not.toHaveClass("flash-up");
    rerender(<Watchlist {...props} prices={price("AAPL", 99)} />);
    expect(cell).toHaveClass("flash-down");
    vi.useRealTimers();
  });

  it("calls add with the uppercased ticker and remove for a row", async () => {
    const user = userEvent.setup();
    render(<Watchlist {...props} prices={{}} />);
    await user.type(screen.getByTestId("watchlist-add-input"), " pypl ");
    await user.click(screen.getByTestId("watchlist-add-button"));
    expect(props.onAdd).toHaveBeenCalledWith("PYPL");
    await user.click(screen.getByTestId("watchlist-remove-AAPL"));
    expect(props.onRemove).toHaveBeenCalledWith("AAPL");
  });
});

describe("api watchlist calls", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("posts and deletes against the watchlist endpoints", async () => {
    const fetchMock = vi.fn(async (_url: string, init?: RequestInit) =>
      init?.method === "DELETE" ? new Response(null, { status: 204 }) : Response.json({ ticker: "PYPL", price: null, added_at: "" }));
    vi.stubGlobal("fetch", fetchMock);
    await api.addTicker("PYPL");
    await api.removeTicker("PYPL");
    expect(fetchMock.mock.calls[0][0]).toBe("/api/watchlist");
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: "POST", body: JSON.stringify({ ticker: "PYPL" }) });
    expect(fetchMock.mock.calls[1]).toEqual(["/api/watchlist/PYPL", expect.objectContaining({ method: "DELETE" })]);
  });

  it("raises the API detail as the error message", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => Response.json({ detail: "Unknown ticker ZZZZ" }, { status: 400 })));
    await expect(api.addTicker("ZZZZ")).rejects.toThrow("Unknown ticker ZZZZ");
  });
});

describe("TradeBar", () => {
  it("shows API errors inline", async () => {
    const user = userEvent.setup();
    const onTrade = vi.fn(async () => { throw new Error("Insufficient cash"); });
    render(<TradeBar ticker="AAPL" onTrade={onTrade} />);
    await user.type(screen.getByTestId("trade-quantity"), "1000");
    await user.click(screen.getByTestId("trade-buy"));
    expect(onTrade).toHaveBeenCalledWith("AAPL", 1000, "buy");
    expect(await screen.findByTestId("trade-error")).toHaveTextContent("Insufficient cash");
  });
});
