# FinAlly — AI Trading Workstation

## Project Specification

## 1. Vision

FinAlly (Finance Ally) is a visually stunning AI-powered trading workstation that streams live market data, lets users trade a simulated portfolio, and integrates an LLM chat assistant that can analyze positions and execute trades on the user's behalf. It looks and feels like a modern Bloomberg terminal with an AI copilot.

It is built entirely by Coding Agents demonstrating how orchestrated AI agents can produce a production-quality full-stack application. Agents interact through files in `planning/`.

## 2. User Experience

### First Launch

The user runs a single Docker command (or a provided start script). A browser opens to `http://localhost:8000`. No login, no signup. They immediately see:

- A watchlist of 10 default tickers with live-updating prices in a grid
- $10,000 in virtual cash
- A dark, data-rich trading terminal aesthetic
- An AI chat panel ready to assist

### What the User Can Do

- **Watch prices stream** — prices flash green (uptick) or red (downtick) with subtle CSS animations that fade
- **View sparkline mini-charts** — price action beside each ticker in the watchlist, accumulated on the frontend from the SSE stream since page load (sparklines fill in progressively)
- **Click a ticker** to see a larger detailed chart in the main chart area (same since-page-load data as the sparkline)
- **Buy and sell shares** — market orders only, instant fill at current price, no fees, no confirmation dialog
- **Monitor their portfolio** — a heatmap (treemap) showing positions sized by weight and colored by P&L, plus a P&L chart tracking total portfolio value over time
- **View a positions table** — ticker, quantity, average cost, current price, unrealized P&L, unrealized P&L % (relative to cost)
- **Chat with the AI assistant** — ask about their portfolio, get analysis, and have the AI execute trades and manage the watchlist through natural language
- **Manage the watchlist** — add/remove tickers manually or via the AI chat

### Visual Design

- **Dark theme**: backgrounds around `#0d1117` or `#1a1a2e`, muted gray borders, no pure black
- **Price flash animations**: brief green/red background highlight on price change, fading over ~500ms via CSS transitions
- **Connection status indicator**: a small colored dot (green = connected, yellow = reconnecting, red = disconnected) visible in the header
- **Professional, data-dense layout**: inspired by Bloomberg/trading terminals — every pixel earns its place
- **Responsive but desktop-first**: optimized for wide screens, functional on tablet

### Color Scheme
- Accent Yellow: `#ecad0a`
- Blue Primary: `#209dd7`
- Purple Secondary: `#753991` (submit buttons)

## 3. Architecture Overview

### Single Container, Single Port

```
┌─────────────────────────────────────────────────┐
│  Docker Container (port 8000)                   │
│                                                 │
│  FastAPI (Python/uv)                            │
│  ├── /api/*          REST endpoints             │
│  ├── /api/stream/*   SSE streaming              │
│  └── /*              Static file serving        │
│                      (Next.js export)           │
│                                                 │
│  SQLite database (named Docker volume)          │
│  Background tasks: market data, snapshots       │
└─────────────────────────────────────────────────┘
```

- **Frontend**: Next.js with TypeScript, built as a static export (`output: 'export'`), served by FastAPI as static files
- **Backend**: FastAPI (Python), managed as a `uv` project
- **Database**: SQLite, single file at `db/finally.db`, persisted in a named Docker volume
- **Real-time data**: Server-Sent Events (SSE) — simpler than WebSockets, one-way server→client push, works everywhere
- **AI integration**: LiteLLM → Groq (primary) with OpenRouter fallback, using structured outputs for trade execution
- **Market data**: Environment-variable driven — simulator by default, real data via Massive API if key provided

### Startup Sequence

The FastAPI lifespan runs these steps once, in order:

1. Initialize the database (create tables and seed if missing)
2. Read the tracked tickers: `watchlist ∪ positions`
3. Create the `PriceCache` and the market data source (simulator or Massive)
4. `start(tickers)` on the source
5. Start the 30 s portfolio snapshot task (Section 7)
6. Include the API routers
7. Mount the static frontend at `/` (last, so it never shadows `/api/*`)

On shutdown, cancel the snapshot task and `stop()` the source.

### Why These Choices

| Decision | Rationale |
|---|---|
| SSE over WebSockets | One-way push is all we need; simpler, no bidirectional complexity, universal browser support |
| Static Next.js export | Single origin, no CORS issues, one port, one container, simple deployment |
| SQLite over Postgres | No auth = no multi-user = no need for a database server; self-contained, zero config |
| Single Docker container | Students run one command; no service orchestration |
| uv for Python | Fast, modern Python project management; reproducible lockfile; what students should learn |
| Market orders only | Eliminates order book, limit order logic, partial fills — dramatically simpler portfolio math |

---

## 4. Directory Structure

```
finally/
├── frontend/                 # Next.js TypeScript project (static export)
├── backend/                  # FastAPI uv project (Python)
│   └── db/                   # Schema definitions, seed data, init logic
├── planning/                 # Project-wide documentation for agents
│   ├── PLAN.md               # This document
│   └── ...                   # Additional agent reference docs
├── scripts/
│   ├── start_mac.sh          # Launch Docker container (macOS/Linux)
│   ├── stop_mac.sh           # Stop Docker container (macOS/Linux)
│   ├── start_windows.ps1     # Launch Docker container (Windows PowerShell)
│   └── stop_windows.ps1      # Stop Docker container (Windows PowerShell)
├── test/                     # Playwright E2E tests (run locally against the app container)
├── db/                       # SQLite location for local non-Docker runs
│   └── .gitkeep              # Directory exists in repo; *.db files are gitignored
├── Dockerfile                # Multi-stage build (Node → Python)
├── .env                      # Environment variables (gitignored)
├── .env.example              # Committed; lists every variable with empty values
└── .gitignore                # Includes .env and db/*.db
```

### Key Boundaries

- **`frontend/`** is a self-contained Next.js project. It knows nothing about Python. It talks to the backend via `/api/*` endpoints and `/api/stream/*` SSE endpoints. Internal structure is up to the Frontend Engineer agent.
- **`backend/`** is a self-contained uv project with its own `pyproject.toml`. It owns all server logic including database initialization, schema, seed data, API routes, SSE streaming, market data, and LLM integration. Internal structure is up to the Backend/Market Data agents.
- **`backend/db/`** contains schema SQL definitions and seed logic. The backend initializes the database at startup (see Section 3).
- **`db/`** at the top level holds `finally.db` for local runs. Inside Docker, the database lives at `/app/db/finally.db` on a named volume.
- **`planning/`** contains project-wide documentation, including this plan. All agents reference files here as the shared contract.
- **`test/`** contains Playwright E2E tests. Unit tests live within `frontend/` and `backend/` respectively, following each framework's conventions.
- **`scripts/`** contains start/stop scripts that wrap Docker commands.

---

## 5. Environment Variables

```bash
# Required: at least one of these (Groq primary, OpenRouter fallback)
GROQ_API_KEY=your-groq-api-key-here
OPENROUTER_API_KEY=your-openrouter-api-key-here

# Optional: Massive (Polygon.io) API key for real market data
# If not set, the built-in market simulator is used (recommended for most users)
MASSIVE_API_KEY=

# Optional: Set to "true" for deterministic mock LLM responses (testing)
LLM_MOCK=false
```

### Behavior

- If `MASSIVE_API_KEY` is set and non-empty → backend uses Massive REST API for market data
- If `MASSIVE_API_KEY` is absent or empty → backend uses the built-in market simulator
- If `LLM_MOCK=true` → backend returns deterministic mock LLM responses (for E2E tests)
- At least one key (Groq or OpenRouter) is required; with only one key there is no fallback
- Neither the Groq nor the OpenRouter key is needed when `LLM_MOCK=true`
- In Docker, variables are passed with `docker run --env-file .env`; the `.env` file is never copied into the image. Local runs read `.env` from the project root via `python-dotenv`.

---

## 6. Market Data

### Two Implementations, One Interface

Both the simulator and the Massive client implement the same abstract interface. The backend selects which to use based on the environment variable. All downstream code (SSE streaming, price cache, frontend) is agnostic to the source.

### Simulator (Default)

- Generates prices using geometric Brownian motion (GBM) with configurable drift and volatility per ticker
- Updates at ~500ms intervals
- Correlated moves across tickers (e.g., tech stocks move together)
- Occasional random "events" — sudden 2-5% moves on a ticker for drama
- Starts from realistic seed prices (e.g., AAPL ~$190, GOOGL ~$175, etc.); unknown tickers get a random seed price
- Runs as an in-process background task — no external dependencies

### Massive API (Optional)

- REST API polling (not WebSocket) — simpler, works on all tiers
- Polls for all tracked tickers on a configurable interval
- Free tier (5 calls/min): poll every 15 seconds
- Paid tiers: poll every 2-15 seconds depending on tier
- Parses REST response into the same format as the simulator
- `add_ticker` fetches a single-ticker snapshot before adding the ticker. If Massive does not know the symbol, it raises `ValueError` and the ticker is not added; the API returns 400 ("Unknown ticker X"). Otherwise the snapshot seeds the cache, so the new ticker has a price immediately (like the simulator) and "add and buy" works in one chat turn.
- The simulator accepts any well-formed symbol.

### Tracked Tickers

- The data source tracks `watchlist ∪ positions`, so held positions always have live prices for valuation and selling.
- Removing a ticker from the watchlist only removes it from the data source if no position is held.
- When a sell closes a position on a ticker that is not on the watchlist, the ticker is removed from the data source.
- Tickers are uppercased and trimmed at the API/LLM boundary before reaching the data source.

### Shared Price Cache

- A single background task (simulator or Massive poller) writes to an in-memory price cache
- The cache holds the latest price (rounded to 2 decimals), previous price, and timestamp for each ticker
- SSE streams read from this cache and push updates to connected clients
- This architecture supports future multi-user scenarios without changes to the data layer

### SSE Streaming

- Endpoint: `GET /api/stream/prices`
- Long-lived SSE connection; client uses native `EventSource` API; the server sends `retry: 1000` so the browser reconnects after 1 s
- Every ~500ms, **if the cache changed**, the server sends **one event holding every tracked ticker**:

```
data: {"AAPL": {"ticker": "AAPL", "price": 190.5, "previous_price": 190.42, "timestamp": 1792839000.123, "change": 0.08, "change_percent": 0.042, "direction": "up"}, "GOOGL": {...}, ...}
```

- `timestamp` is Unix seconds (float). `change`, `change_percent` and `direction` are relative to the previous tick, not the trading day. The frontend only needs `ticker`, `price`, `previous_price` and `timestamp`; the rest is a convenience.

---

## 7. Database

### SQLite, Initialized at Startup

On startup the backend creates any missing tables and seeds default data if the database is empty (see Section 3). This means:

- No separate migration step
- No manual database setup
- Fresh Docker volumes start with a clean, seeded database automatically

### Schema

All tables except `users_profile` include a `user_id` column defaulting to `"default"`; in `users_profile`, `id` is the user id. This is hardcoded for now (single-user) but enables future multi-user support without schema migration. All timestamps are stored as ISO 8601 UTC strings.

**users_profile** — User state (cash balance)
- `id` TEXT PRIMARY KEY (default: `"default"`)
- `cash_balance` REAL (default: `10000.0`)

**watchlist** — Tickers the user is watching
- `user_id` TEXT (default: `"default"`)
- `ticker` TEXT
- `added_at` TEXT
- PRIMARY KEY `(user_id, ticker)`

**positions** — Current holdings (one row per ticker per user; the row is deleted when the position is fully closed)
- `user_id` TEXT (default: `"default"`)
- `ticker` TEXT
- `quantity` REAL (fractional shares supported)
- `avg_cost` REAL
- `updated_at` TEXT
- PRIMARY KEY `(user_id, ticker)` — upserts use `INSERT ... ON CONFLICT DO UPDATE`

**trades** — Trade history (append-only log)
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `ticker` TEXT
- `side` TEXT (`"buy"` or `"sell"`)
- `quantity` REAL (fractional shares supported)
- `price` REAL
- `executed_at` TEXT

**portfolio_snapshots** — Portfolio value over time (for P&L chart)
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `total_value` REAL
- `recorded_at` TEXT

**chat_messages** — Conversation history with LLM
- `id` TEXT PRIMARY KEY (UUID)
- `user_id` TEXT (default: `"default"`)
- `role` TEXT (`"user"` or `"assistant"`)
- `content` TEXT
- `actions` TEXT (JSON — the executed action results, same shape as in the `/api/chat` response; null for user messages)
- `created_at` TEXT

### Portfolio Snapshots

A snapshot is recorded:
- every 30 s by a single `asyncio` background task started in the FastAPI lifespan (and cancelled on shutdown), with the first one at startup,
- immediately after each trade (inside the trade transaction).

### Default Seed Data

- One user profile: `id="default"`, `cash_balance=10000.0`
- Ten watchlist entries: AAPL, GOOGL, MSFT, AMZN, TSLA, NVDA, META, JPM, V, NFLX

---

## 8. API Endpoints

### Conventions

- Every endpoint and LLM action uppercases and trims the ticker before use.
- A valid ticker is 1-10 characters of `A-Z`, `0-9`, `.` or `-`, starting with a letter. With Massive, a symbol it does not know is rejected with 400; the simulator accepts any valid symbol.
- Validation errors return HTTP 400 with `{"detail": "..."}` (FastAPI default). An unknown ticker on DELETE returns 404. LLM unavailable returns 503.
- REST timestamps are ISO 8601 UTC strings (e.g. `"2026-10-24T14:03:12Z"`). Only the SSE stream uses Unix seconds.
- Money values (cash, prices, values, P&L) are rounded to 2 decimals in responses, `avg_cost` to 4 decimals, percentages to 2 decimals. Quantities are returned as stored.

### Market Data
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/stream/prices` | SSE stream of live price updates (Section 6) |

### Portfolio
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/portfolio` | Current positions, cash balance, total value, unrealized P&L |
| POST | `/api/portfolio/trade` | Execute a trade: `{ticker, quantity, side}` |
| GET | `/api/portfolio/history` | Portfolio value snapshots over time (for P&L chart) |

`GET /api/portfolio`:
```json
{
  "cash_balance": 8095.0,
  "positions_value": 1955.3,
  "total_value": 10050.3,
  "unrealized_pnl": 50.3,
  "positions": [
    {"ticker": "AAPL", "quantity": 10, "avg_cost": 190.5, "current_price": 195.53,
     "market_value": 1955.3, "unrealized_pnl": 50.3, "unrealized_pnl_percent": 2.64}
  ]
}
```

`POST /api/portfolio/trade` request `{"ticker": "AAPL", "quantity": 10, "side": "buy"}`, response:
```json
{
  "trade": {"id": "uuid", "ticker": "AAPL", "side": "buy", "quantity": 10, "price": 190.5,
            "executed_at": "2026-10-24T14:03:12Z"},
  "portfolio": { "...": "same shape as GET /api/portfolio" }
}
```

`GET /api/portfolio/history` returns the most recent 1000 snapshots, oldest first:
```json
{"snapshots": [{"total_value": 10000.0, "recorded_at": "2026-10-24T14:00:00Z"}]}
```

### Trade Execution

Manual trades and LLM trades call the same service function. It runs in one SQLite transaction (`BEGIN IMMEDIATE`): read cash and position, validate, write cash, position, trade row and snapshot. That is enough for a single user; no extra locking.

- `quantity` must be > 0. No minimum size and no rounding of quantity.
- The ticker must have a price in the cache; otherwise 400 ("No price yet for X").
- The fill price is the cached price (already rounded to 2 decimals).
- Buy: requires `cash_balance >= quantity × price`. The new `avg_cost` is the quantity-weighted average of the old cost and the fill price.
- Sell: requires `quantity <= held + 1e-6`. If the remaining quantity is below `1e-6`, the position row is deleted. `avg_cost` does not change on a sell.
- Cash and `avg_cost` are stored unrounded; rounding happens only in responses.

### Watchlist
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/watchlist` | Current watchlist tickers with latest prices |
| POST | `/api/watchlist` | Add a ticker: `{ticker}` |
| DELETE | `/api/watchlist/{ticker}` | Remove a ticker |

`GET /api/watchlist` (`price` is null until the ticker receives its first price):
```json
{"watchlist": [{"ticker": "AAPL", "price": 190.5, "added_at": "2026-10-24T14:00:00Z"}]}
```

`POST /api/watchlist` returns 200 with the entry (same shape as one list item). Adding a ticker already on the list is not an error and returns the existing entry. `DELETE` returns 204, or 404 if the ticker is not on the watchlist.

### Chat
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/chat` | Send `{message}`, receive the reply plus the result of every action |
| GET | `/api/chat` | The last 50 messages, oldest first, for the chat panel after a reload |

`POST /api/chat` response:
```json
{
  "message": "Bought 10 AAPL at $190.50 and added PYPL to your watchlist.",
  "watchlist_changes": [{"ticker": "PYPL", "action": "add", "status": "ok", "error": null}],
  "trades": [{"ticker": "AAPL", "side": "buy", "quantity": 10, "status": "ok", "price": 190.5, "error": null}]
}
```
A failed action has `"status": "error"`, `"price": null` and an `error` string.

`GET /api/chat`:
```json
{"messages": [{"id": "uuid", "role": "assistant", "content": "...",
               "actions": {"watchlist_changes": [], "trades": []}, "created_at": "2026-10-24T14:03:12Z"}]}
```

There is no endpoint to clear the chat.

### System
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Health check (for Docker/deployment): `{"status": "ok"}` |

---

## 9. LLM Integration

When writing code to make calls to LLMs, follow the `groq-llm` and `openrouter-llm` skills (in `.claude/skills/`) to use LiteLLM with Groq as the primary provider (`groq/openai/gpt-oss-120b`) and OpenRouter's free model (`openrouter/nvidia/nemotron-3-super-120b-a12b:free`; the free gpt-oss-120b was withdrawn) as the fallback when Groq is rate-limited or unavailable. Only use free models: never use a paid model or pin a paid inference provider such as Cerebras. Use Structured Outputs so that you can interpret the results.

Fallback and error handling follow the skills: a LiteLLM `Router` with `fallbacks`; a `RateLimitError` after retries maps to HTTP 503; a `ValidationError` on malformed output is re-asked once before returning a friendly error.

The GROQ_API_KEY and OPENROUTER_API_KEY live in the `.env` file in the project root, which is gitignored; `.env.example` lists them empty. Never commit keys.

OpenRouter's free tier allows about 50 requests per day, so the fallback is a safety net, not a second engine. Every automated test (unit and E2E) must use mocks or `LLM_MOCK=true`, never a live key.

### How It Works

When the user sends a chat message, the backend:

1. Loads the user's current portfolio context (cash, positions with P&L, watchlist with live prices, total portfolio value)
2. Loads the last 20 messages from `chat_messages` (message text only; earlier `actions` are not replayed, since the fresh portfolio context covers them)
3. Constructs a prompt with a system message, portfolio context, conversation history, and the user's new message
4. Calls the LLM via LiteLLM → Groq or OpenRouter, requesting structured output
5. Parses the complete structured JSON response into a Pydantic model
6. Executes the actions: all watchlist changes first, then trades in listed order. Each action runs independently; one failure does not roll back the others
7. Stores the user message, and the assistant message with the action results in `actions`, in `chat_messages`
8. Returns the reply and action results to the frontend (Section 8; no token-by-token streaming)

### Structured Output Schema

Groq strict `json_schema` mode requires every field to be present, so both arrays are required and empty when there is nothing to do:

```python
class Trade(BaseModel):
    ticker: str
    side: Literal["buy", "sell"]
    quantity: float

class WatchlistChange(BaseModel):
    ticker: str
    action: Literal["add", "remove"]

class ChatReply(BaseModel):
    message: str
    trades: list[Trade]
    watchlist_changes: list[WatchlistChange]
```

Each trade goes through the same validation as manual trades (Section 8). If an action fails, its error is included in the response so the user sees why.

### Auto-Execution

Trades specified by the LLM execute automatically — no confirmation dialog. This is a deliberate design choice:
- It's a simulated environment with fake money, so the stakes are zero
- It creates an impressive, fluid demo experience
- It demonstrates agentic AI capabilities

### System Prompt Guidance

The LLM should be prompted as "FinAlly, an AI trading assistant" with instructions to:
- Analyze portfolio composition, risk concentration, and P&L
- Suggest trades with reasoning
- Execute trades when the user asks or agrees
- Manage the watchlist proactively
- Be concise and data-driven in responses
- Always respond with valid structured JSON

### LLM Mock Mode

When `LLM_MOCK=true`, the backend returns deterministic mock responses instead of calling Groq/OpenRouter. The mock is a single function in `llm.py` that returns the same `ChatReply` model as the real call, so the chat route has no mock branch:

- Message contains "buy" (case-insensitive) → buy 1 AAPL
- Message contains "sell" → sell 1 AAPL
- Anything else → a fixed message with no actions

This enables fast, free, reproducible E2E tests, development without an API key, and CI pipelines.

---

## 10. Frontend Design

### Layout

The frontend is a single-page application with a dense, terminal-inspired layout. The specific component architecture and layout system is up to the Frontend Engineer, but the UI should include these elements:

- **Watchlist panel** — grid/table of watched tickers with: ticker symbol, current price (flashing green/red on change), change % since page load (from the first SSE price this session), and a sparkline mini-chart. A ticker with no price yet shows "—".
- **Main chart area** — larger chart for the currently selected ticker, showing price since page load. Clicking a ticker in the watchlist selects it here.
- **Portfolio heatmap** — treemap visualization where each rectangle is a position, sized by portfolio weight, colored by P&L (green = profit, red = loss)
- **P&L chart** — line chart showing total portfolio value over time, from `GET /api/portfolio/history`. Refetch after each trade and every 30 s.
- **Positions table** — ticker, quantity, avg cost, current price, unrealized P&L, unrealized P&L %
- **Trade bar** — simple input area: ticker field, quantity field, buy button, sell button. Market orders, instant fill. Errors from the API are shown inline.
- **AI chat panel** — docked/collapsible sidebar. Message input, scrolling conversation history (loaded from `GET /api/chat` on page load), loading indicator while waiting for the reply. Replies can take up to a minute when the OpenRouter fallback is used. A 503 shows "The assistant is busy, try again in a moment". Trade executions and watchlist changes are shown inline as confirmations or errors.
- **Header** — portfolio total value (updating live), connection status indicator, cash balance

### Technical Notes

- Use `EventSource` for SSE connection to `/api/stream/prices`
- Keep one per-ticker price buffer on the frontend, filled from SSE; sparklines and the main chart both read it. There is no price-history endpoint.
- Live values are computed on the frontend: header total = `cash + Σ quantity × live price`; unrealized P&L in the positions table and heatmap also uses live SSE prices. `/api/portfolio` supplies cash, quantities and average costs.
- Connection dot maps to `EventSource.readyState`: `OPEN` = green, `CONNECTING` = yellow, `CLOSED` = red.
- Charts: Lightweight Charts (canvas-based, finance-oriented) for the price and P&L charts. Treemap: Recharts `Treemap` or a small hand-rolled squarified layout.
- Price flash effect: on receiving a new price, briefly apply a CSS class with background color transition, then remove it
- All API calls go to the same origin (`/api/*`) — no CORS configuration needed
- Tailwind CSS for styling with a custom dark theme

---

## 11. Docker & Deployment

### Multi-Stage Dockerfile

```
Stage 1: Node 24 LTS slim
  - Copy frontend/
  - npm ci && npm run build (produces static export in frontend/out)

Stage 2: Python 3.13 slim
  - Install uv
  - Copy backend/ to /app (3.13 matches the interpreter uv uses locally)
  - uv sync --frozen (uses the lockfile exactly; dev extras are not installed)
  - Copy frontend/out to /app/static
  - Expose port 8000
  - CMD: uvicorn serving FastAPI app
```

FastAPI serves all API routes and mounts `StaticFiles(directory="/app/static", html=True)` at `/` after the API routers.

### Docker Volume

The SQLite database persists in a named Docker volume:

```bash
docker run -v finally-data:/app/db -p 8000:8000 --env-file .env finally
```

The backend writes `/app/db/finally.db`. A named volume avoids Windows bind-mount path issues.

### Start/Stop Scripts

**`scripts/start_mac.sh`** (macOS/Linux):
- Builds the Docker image if not already built (or if `--build` flag passed)
- Runs the container with the volume, port mapping, and `--env-file .env`
- Prints the URL to access the app
- Optionally opens the browser

**`scripts/stop_mac.sh`** (macOS/Linux):
- Stops and removes the running container
- Does NOT remove the volume (data persists)

**`scripts/start_windows.ps1`** / **`scripts/stop_windows.ps1`**: PowerShell equivalents for Windows.

All scripts should be idempotent — safe to run multiple times.

---

## 12. Testing Strategy

### Unit Tests (within `frontend/` and `backend/`)

**Backend (pytest)**:
- Market data: simulator generates valid prices, GBM math is correct, Massive API response parsing works, both implementations conform to the abstract interface
- Portfolio: trade execution logic, P&L calculations, edge cases (selling more than owned, buying with insufficient cash, selling at a loss, selling the full position deletes the row)
- LLM: structured output parsing handles all valid schemas, graceful handling of malformed responses, trade validation within chat flow, action ordering and independent failures
- API routes: correct status codes, response shapes, error handling

**Frontend (React Testing Library or similar)**:
- Component rendering with mock data
- Price flash animation triggers correctly on price changes
- Watchlist CRUD operations
- Portfolio display calculations
- Chat message rendering and loading state

### E2E Tests (in `test/`)

**Infrastructure**: Playwright runs locally (`npx playwright test`) against the running app container. A compose file for CI can be added later if needed.

**Environment**: The app container runs with `LLM_MOCK=true`. Each E2E run starts with a fresh volume, and tests do not depend on each other's trades.

**Key Scenarios**:
- Fresh start: default watchlist appears, $10k balance shown, prices are streaming, connection dot is green
- Add and remove a ticker from the watchlist
- Buy shares: cash decreases, position appears, portfolio updates
- Sell shares: cash increases, position updates or disappears
- Portfolio visualization: heatmap renders with correct colors, P&L chart has data points
- AI chat (mocked): send a message containing "buy", receive a response, trade execution appears inline

SSE reconnection is browser behaviour (`EventSource`), not app code, so it has no E2E test.
