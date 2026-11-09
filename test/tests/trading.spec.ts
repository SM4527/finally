import { expect, test } from "@playwright/test";
import { heldQuantity, openWithPrice, readMoney, trade } from "./helpers";

test("buy shares: cash decreases and position appears", async ({ page, request }) => {
  const ticker = "MSFT";
  await openWithPrice(page, ticker);
  const cashBefore = await readMoney(page, "header-cash");
  const qtyBefore = await heldQuantity(request, ticker);

  await trade(page, ticker, 2, "buy");

  await expect(page.getByTestId(`position-row-${ticker}`)).toBeVisible();
  await expect.poll(() => readMoney(page, "header-cash")).toBeLessThan(cashBefore);
  expect(await heldQuantity(request, ticker)).toBeCloseTo(qtyBefore + 2);
  await expect(page.getByTestId("positions-table")).toContainText(ticker);
});

test("sell shares: cash increases, position updates then disappears", async ({ page, request }) => {
  const ticker = "NVDA";
  await openWithPrice(page, ticker);
  const qtyStart = await heldQuantity(request, ticker);

  await trade(page, ticker, 3, "buy");
  await expect(page.getByTestId(`position-row-${ticker}`)).toBeVisible();
  await expect.poll(() => heldQuantity(request, ticker)).toBeCloseTo(qtyStart + 3);
  const cashAfterBuy = await readMoney(page, "header-cash");

  await trade(page, ticker, 1, "sell");
  await expect.poll(() => readMoney(page, "header-cash")).toBeGreaterThan(cashAfterBuy);
  expect(await heldQuantity(request, ticker)).toBeCloseTo(qtyStart + 2);
  await expect(page.getByTestId(`position-row-${ticker}`)).toBeVisible();

  await trade(page, ticker, qtyStart + 2, "sell");
  await expect(page.getByTestId(`position-row-${ticker}`)).toHaveCount(0);
  expect(await heldQuantity(request, ticker)).toBe(0);
});

test("selling more than held shows an inline error", async ({ page, request }) => {
  const ticker = "NFLX";
  await openWithPrice(page, ticker);
  const held = await heldQuantity(request, ticker);

  await trade(page, ticker, held + 1000, "sell");

  await expect(page.getByTestId("trade-error")).toBeVisible();
  await expect(page.getByTestId("trade-error")).not.toBeEmpty();
  expect(await heldQuantity(request, ticker)).toBe(held);
});
