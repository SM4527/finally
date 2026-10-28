# FinAlly — AI Trading Workstation

An AI-powered trading workstation that streams live market data, lets you trade a simulated $10k portfolio, and includes an LLM chat assistant that can analyze positions and execute trades in natural language. Built entirely by coding agents.

> Status: the market data component is complete. The rest of the platform is in progress — see [planning/PLAN.md](planning/PLAN.md).

## Features

- Live price streaming over SSE with green/red flash animations and sparklines
- Simulated portfolio: market orders, instant fills, no fees
- Portfolio heatmap, P&L chart and positions table
- AI chat assistant that analyzes holdings and auto-executes trades and watchlist changes
- Dark, data-dense terminal aesthetic

## Architecture

One Docker container on port 8000:

- **Frontend**: Next.js + TypeScript + Tailwind (static export)
- **Backend**: FastAPI (Python, `uv`) with SSE streaming
- **Database**: SQLite, created and seeded at startup
- **AI**: LiteLLM → Groq (`gpt-oss-120b`), OpenRouter free model as fallback, structured outputs
- **Market data**: built-in GBM simulator by default, Massive (Polygon.io) API if a key is set

## Quick Start

```bash
cp .env.example .env    # add GROQ_API_KEY and/or OPENROUTER_API_KEY
docker build -t finally .
docker run -v finally-data:/app/db -p 8000:8000 --env-file .env finally
```

Open http://localhost:8000. Start/stop scripts will live in `scripts/`.

## Environment Variables

| Variable | Required | Description |
|---|---|---|
| `GROQ_API_KEY` | One of the two | Primary LLM provider |
| `OPENROUTER_API_KEY` | One of the two | Fallback LLM provider |
| `MASSIVE_API_KEY` | No | Real market data; empty uses the simulator |
| `LLM_MOCK` | No | `true` for deterministic mock LLM replies (tests) |

## Development

```bash
cd backend
uv sync --extra dev
uv run --extra dev pytest
```

## Project Structure

```
finally/
├── frontend/    # Next.js static export
├── backend/     # FastAPI uv project
├── planning/    # Specs and agent contracts
├── test/        # Playwright E2E tests
├── db/          # SQLite file for local runs
└── scripts/     # Start/stop helpers
```

## License

See [LICENSE](LICENSE).
