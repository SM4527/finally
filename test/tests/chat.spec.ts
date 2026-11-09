import { expect, test } from "@playwright/test";
import { heldQuantity, openWithPrice } from "./helpers";

test("mocked AI chat executes a buy and shows it inline", async ({ page, request }) => {
  const history = page.waitForResponse((r) => r.url().endsWith("/api/chat") && r.request().method() === "GET");
  await openWithPrice(page, "AAPL");
  await history;
  const qtyBefore = await heldQuantity(request, "AAPL");
  const messagesBefore = await page.getByTestId("chat-message").count();

  await page.getByTestId("chat-input").fill("Please buy some Apple");
  await page.getByTestId("chat-send").click();

  await expect(page.getByTestId("chat-message")).toHaveCount(messagesBefore + 2);
  await expect(page.getByTestId("chat-loading")).toHaveCount(0);
  await expect(page.getByTestId("chat-message").last()).not.toBeEmpty();
  await expect(page.getByTestId("chat-message").last()).toHaveAttribute("data-role", "assistant");
  await expect(page.getByTestId("chat-action").last()).toContainText("AAPL");
  await expect(page.getByTestId("chat-action").last()).toHaveAttribute("data-status", "ok");

  expect(await heldQuantity(request, "AAPL")).toBeCloseTo(qtyBefore + 1);
  await expect(page.getByTestId("position-row-AAPL")).toBeVisible();

  await page.reload();
  await expect(page.getByTestId("chat-message")).toHaveCount(messagesBefore + 2);
});
