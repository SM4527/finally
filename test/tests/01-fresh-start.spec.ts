import { expect, test } from "@playwright/test";
import { DEFAULT_TICKERS, readMoney } from "./helpers";

test("fresh start shows default watchlist, $10k cash and live prices", async ({ page }) => {
  await page.goto("/");

  for (const ticker of DEFAULT_TICKERS) {
    await expect(page.getByTestId(`watchlist-row-${ticker}`)).toBeVisible();
  }
  await expect(page.locator('[data-testid^="watchlist-row-"]')).toHaveCount(10);

  await expect(page.getByTestId("header-cash")).toContainText("10,000");
  expect(await readMoney(page, "header-cash")).toBe(10000);

  await expect(page.getByTestId("connection-dot")).toHaveAttribute("data-state", "open");

  const prices = () =>
    Promise.all(DEFAULT_TICKERS.map((t) => page.getByTestId(`watchlist-price-${t}`).innerText()));
  await expect.poll(async () => (await prices()).every((p) => /\d/.test(p))).toBe(true);
  const first = await prices();
  await expect.poll(async () => (await prices()).join() !== first.join()).toBe(true);

  await expect(page.getByTestId("main-chart")).toBeVisible();
  await expect.poll(async () => Number(await page.getByTestId("main-chart").getAttribute("data-points"))).toBeGreaterThan(1);
  expect(await readMoney(page, "header-total")).toBeGreaterThan(0);
});
