import { expect, test } from "@playwright/test";
import { openWithPrice, trade } from "./helpers";

test("heatmap shows held positions and P&L chart has data", async ({ page, request }) => {
  const ticker = "JPM";
  await openWithPrice(page, ticker);
  await trade(page, ticker, 1, "buy");
  await expect(page.getByTestId(`position-row-${ticker}`)).toBeVisible();

  const heatmap = page.getByTestId("heatmap");
  await expect(heatmap).toBeVisible();
  await expect(heatmap).toContainText(ticker);

  const history = await (await request.get("/api/portfolio/history")).json();
  expect(history.snapshots.length).toBeGreaterThanOrEqual(2);

  const chart = page.getByTestId("pnl-chart");
  await expect(chart).toBeVisible();
  await expect(chart.locator("canvas").first()).toBeVisible();
  await expect.poll(async () => Number(await chart.getAttribute("data-points"))).toBeGreaterThanOrEqual(2);
});

test("heatmap colours positions by P&L sign", async ({ page }) => {
  const ticker = "GOOGL";
  await openWithPrice(page, ticker);
  await trade(page, ticker, 1, "buy");
  const tile = page.getByTestId(`heatmap-tile-${ticker}`);
  await expect(tile).toBeVisible();

  const sample = () =>
    tile.evaluate((el) => {
      const probe = document.createElement("div");
      probe.style.color = getComputedStyle(el).backgroundColor;
      document.body.appendChild(probe);
      const rgb = getComputedStyle(probe).color.match(/\d+(\.\d+)?/g)!.map(Number);
      probe.remove();
      return { text: el.textContent ?? "", rgb };
    });

  await expect
    .poll(async () => /[1-9]/.test((await sample()).text.replace(ticker, "")), { timeout: 20_000 })
    .toBe(true);
  const { text, rgb } = await sample();
  const [r, g] = rgb;
  if (text.includes("-")) expect(r, `tile "${text}" should be red`).toBeGreaterThan(g);
  else expect(g, `tile "${text}" should be green`).toBeGreaterThan(r);
});
