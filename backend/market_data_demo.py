"""Live terminal demo of the market data layer.

Uses the simulator, or Massive if MASSIVE_API_KEY is set in the project-root .env.

    uv run market_data_demo.py            # run until Ctrl+C
    uv run market_data_demo.py --seconds 20
"""

import argparse
import asyncio
from pathlib import Path

from dotenv import load_dotenv

from app.market import PriceCache, PriceUpdate, create_market_data_source

TICKERS = ["AAPL", "GOOGL", "MSFT", "AMZN", "TSLA", "NVDA", "META", "JPM", "V", "NFLX"]
GREEN, RED, RESET = "\033[32m", "\033[31m", "\033[0m"
CLEAR = "\033[H\033[2J"


def format_row(update: PriceUpdate, start_price: float) -> str:
    """One table row: price colored by last tick, plus change since the demo started."""
    color = {"up": GREEN, "down": RED}.get(update.direction, "")
    since_start = (update.price - start_price) / start_price * 100
    return (
        f"{update.ticker:<6} {color}{update.price:>10.2f}{RESET}"
        f" {update.change:>+8.2f} {since_start:>+10.2f}%"
    )


def render(cache: PriceCache, start_prices: dict[str, float], elapsed: float) -> str:
    """Full screen: header plus one row per ticker."""
    lines = [
        f"FinAlly market data demo   {elapsed:5.1f}s   (Ctrl+C to quit)",
        "",
        f"{'TICKER':<6} {'PRICE':>10} {'TICK':>8} {'SINCE START':>11}",
    ]
    for ticker, update in sorted(cache.snapshot().items()):
        start = start_prices.setdefault(ticker, update.price)
        lines.append(format_row(update, start))
    return "\n".join(lines)


async def run(seconds: float | None) -> None:
    """Start the data source, redraw the table every 0.5 s, stop on exit."""
    cache = PriceCache()
    source = create_market_data_source(cache)
    await source.start(TICKERS)
    start_prices: dict[str, float] = {}
    loop = asyncio.get_running_loop()
    began = loop.time()
    try:
        while seconds is None or loop.time() - began < seconds:
            print(CLEAR + render(cache, start_prices, loop.time() - began), flush=True)
            await asyncio.sleep(0.5)
    finally:
        await source.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seconds", type=float, help="stop after this many seconds")
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    try:
        asyncio.run(run(args.seconds))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
