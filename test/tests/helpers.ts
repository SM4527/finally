import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const DEFAULT_TICKERS = [
  "AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX",
];

/** Parse a displayed money string such as "$10,000.00" into a number. */
export function parseMoney(text: string): number {
  return Number(text.replace(/[^0-9.-]/g, ""));
}

export async function readMoney(page: Page, testId: string): Promise<number> {
  return parseMoney(await page.getByTestId(testId).innerText());
}

/** Held quantity of a ticker according to the API (0 if no position). */
export async function heldQuantity(request: APIRequestContext, ticker: string): Promise<number> {
  const body = await (await request.get("/api/portfolio")).json();
  const pos = body.positions.find((p: { ticker: string }) => p.ticker === ticker);
  return pos ? pos.quantity : 0;
}

/** Open the app and wait until the ticker shows a live price. */
export async function openWithPrice(page: Page, ticker: string): Promise<void> {
  await page.goto("/");
  await expect(page.getByTestId(`watchlist-price-${ticker}`)).toHaveText(/\d/);
}

export async function trade(page: Page, ticker: string, quantity: number, side: "buy" | "sell") {
  await page.getByTestId("trade-ticker").fill(ticker);
  await page.getByTestId("trade-quantity").fill(String(quantity));
  await page.getByTestId(`trade-${side}`).click();
}
