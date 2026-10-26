# FinAlly Backend

FastAPI backend for the FinAlly AI Trading Workstation.

## Structure

- `app/` - Application code
  - `market/` - Market data subsystem
    - `models.py` - PriceUpdate dataclass
    - `cache.py` - Thread-safe price cache
    - `interface.py` - MarketDataSource abstract interface
    - `simulator.py` - GBM-based market simulator
    - `massive_client.py` - Massive/Polygon.io API client
    - `factory.py` - Data source factory
    - `stream.py` - SSE router factory (`create_stream_router`)
    - `seed_prices.py` - Default ticker prices and parameters

- `tests/` - Unit and integration tests
  - `market/` - Market data tests

## Running Tests

```bash
# Install dependencies
uv sync --extra dev

# Run all tests
uv run --extra dev pytest

# Run with coverage
uv run --extra dev pytest --cov=app --cov-report=html

# Run specific test file
uv run --extra dev pytest tests/market/test_simulator.py

# Run with verbose output
uv run --extra dev pytest -v
```

## Environment Variables

- `MASSIVE_API_KEY` - Optional. If set, use real market data from Massive API. If not set, use the built-in simulator.

## Development

```bash
# Install dependencies
uv sync --extra dev

# Run linter
uv run --extra dev ruff check .

# Format code
uv run --extra dev ruff format .
```
