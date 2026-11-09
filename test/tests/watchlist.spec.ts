import { expect, test } from "@playwright/test";

test("add and remove a ticker from the watchlist", async ({ page }) => {
  const ticker = "PYPL";
  await page.goto("/");
  await expect(page.getByTestId("watchlist-row-AAPL")).toBeVisible();

  await page.getByTestId("watchlist-add-input").fill(" pypl ");
  await page.getByTestId("watchlist-add-button").click();
  await expect(page.getByTestId(`watchlist-row-${ticker}`)).toBeVisible();
  await expect(page.getByTestId(`watchlist-price-${ticker}`)).toHaveText(/\d/);

  await page.reload();
  await expect(page.getByTestId(`watchlist-row-${ticker}`)).toBeVisible();

  await page.getByTestId(`watchlist-remove-${ticker}`).click();
  await expect(page.getByTestId(`watchlist-row-${ticker}`)).toHaveCount(0);

  await page.reload();
  await expect(page.getByTestId("watchlist-row-AAPL")).toBeVisible();
  await expect(page.getByTestId(`watchlist-row-${ticker}`)).toHaveCount(0);
});
