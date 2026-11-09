# FinAlly — the Finance Ally

An AI-powered trading workstation: live market data, a simulated $10,000 portfolio, and an AI chat assistant that can analyze your positions and trade on your behalf. Think Bloomberg terminal with an AI copilot.

FinAlly is built by coding agents that coordinate through the specs in [`planning/`](planning/PLAN.md).

> **Status:** in development. The backend market data layer (simulator, Massive client, price cache, SSE stream) is built and tested. The rest of the app is not yet written, so the Run steps below do not work yet.

## Features

- Live prices streamed over SSE, with green/red flashes and sparklines
- Market orders with instant fills, no fees
- Portfolio heatmap, P&L chart and positions table
- AI chat that can explain your portfolio, place trades and edit your watchlist
- Built-in market simulator by default; real data with a Massive (Polygon.io) key

## Stack

| Layer | Tech |
|---|---|
| Frontend | Next.js + TypeScript (static export), Tailwind, Lightweight Charts |
| Backend | FastAPI, managed with `uv` |
| Database | SQLite |
| AI | LiteLLM → Groq (`gpt-oss-120b`), OpenRouter free-model fallback |
| Deployment | Single Docker container on port 8000 |

## Run

Requires Docker.

1. Copy `.env.example` to `.env` and set `GROQ_API_KEY` and/or `OPENROUTER_API_KEY` (or `LLM_MOCK=true`).
2. Start the app (builds the image on first run; add `--build` / `-Build` to rebuild):
   ```bash
   ./scripts/start_mac.sh        # macOS / Linux
   ./scripts/start_windows.ps1   # Windows PowerShell
   ```
3. Open http://localhost:8000.

Stop with `scripts/stop_mac.sh` or `scripts/stop_windows.ps1`. Data is kept in the `finally-data` Docker volume; `docker volume rm finally-data` resets it.

## Configuration

| Variable | Purpose |
|---|---|
| `GROQ_API_KEY` | Primary LLM provider |
| `OPENROUTER_API_KEY` | Fallback LLM provider |
| `MASSIVE_API_KEY` | Optional real market data; leave empty to use the simulator |
| `MASSIVE_POLL_INTERVAL` | Seconds between Massive polls (default 15, free-tier safe) |
| `LLM_MOCK` | `true` returns canned LLM replies (for tests, no key needed) |

## Backend development

Requires [uv](https://docs.astral.sh/uv/). From `backend/`:

```bash
uv sync --extra dev          # install dependencies, including test tools
uv run pytest -v             # run the unit tests
uv run market_data_demo.py   # live price table in the terminal (Ctrl+C to quit)
```

The demo uses the simulator, or Massive when `MASSIVE_API_KEY` is set in `.env`. Add `--seconds 20` to stop it automatically.

## Project layout

```
frontend/   Next.js app
backend/    FastAPI app (uv project)
planning/   Specs shared by the agents
scripts/    Start/stop scripts
test/       Playwright E2E tests
db/         SQLite file for local runs
```

## License

MIT, see [LICENSE](LICENSE).
