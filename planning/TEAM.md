# Agent Team Contract

Shared contract for the agent team building FinAlly. PLAN.md is the spec; this file fixes file ownership and the Python interfaces between owners so work can proceed in parallel. If you need to change an interface here, message the affected owners first, then update this file.

## Team and file ownership

| Name (SendMessage `to`) | Role | Owns |
|---|---|---|
| `database` | Database Engineer | `backend/app/db/**`, `backend/app/tests/db/**` |
| `backend` | Backend API Engineer | `backend/app/main.py`, `backend/app/portfolio.py`, `backend/app/watchlist.py`, `backend/app/snapshots.py`, `backend/app/routes/` (except `chat.py`), `backend/app/tests/api/**`, `backend/pyproject.toml` |
| `llm` | LLM Engineer | `backend/app/llm.py`, `backend/app/chat.py`, `backend/app/routes/chat.py`, `backend/app/tests/llm/**` |
| `frontend` | Frontend Engineer | `frontend/**` |
| `devops` | DevOps Engineer | `Dockerfile`, `.dockerignore`, `scripts/**`, `docker-compose*.yml`, README run section |
| `tester` | Integration Tester | `test/**` (Playwright) |

The market data layer (`backend/app/market/`, `backend/app/tickers.py`) is finished. Do not change it without telling `backend`. Read `planning/MARKET_DATA_SUMMARY.md`.

Only edit files you own. If you need a change in someone else's file, send them a message. Any agent may `uv add` a dependency; tell `backend` when you do. Do not commit to git; the lead handles commits.

## Environment notes (WSL)

- Python: `cd backend && uv run pytest` (always `uv run`).
- Node is the Windows install: `/mnt/c/Program Files/nodejs/node.exe`, `npm.cmd` and `npx.cmd`. Windows interop is blocked by the Bash sandbox, so node/npm/npx/docker commands need `dangerouslyDisableSandbox: true`. Run them from WSL paths with `cmd.exe /c "cd /d C:\\Users\\Sivan\\projects\\finally\\frontend && npm run build"`, or call `npm.cmd` directly.
- Docker Desktop is running. Use `docker.exe` (Windows binary, also needs `dangerouslyDisableSandbox: true`); plain `docker` fails because WSL integration is off. Docker Desktop on Windows resolves WSL paths poorly, so run builds from the repo root with relative paths (e.g. `docker.exe build -t finally .`). Scripts in `scripts/` should still call plain `docker` for end users.

## Python interfaces

### `app.db` (owner: database)

```python
# app/db/connection.py
def db_path() -> Path            # env FINALLY_DB_PATH, else <repo>/db/finally.db
def connect(path: Path | str | None = None) -> sqlite3.Connection
    # row_factory=sqlite3.Row, isolation_level=None (autocommit; callers run
    # "BEGIN IMMEDIATE" ... "COMMIT" themselves), check_same_thread=False
def init_db(conn) -> None        # create missing tables from schema.sql, seed if empty
def now_iso() -> str             # "2026-10-24T14:03:12Z"

# app/db/repo.py  -- every function takes conn first, user_id="default" kwarg last
get_cash(conn) -> float
set_cash(conn, cash: float) -> None
get_positions(conn) -> list[dict]          # {ticker, quantity, avg_cost, updated_at}
get_position(conn, ticker) -> dict | None
upsert_position(conn, ticker, quantity, avg_cost) -> None
delete_position(conn, ticker) -> None
insert_trade(conn, ticker, side, quantity, price) -> dict   # {id, ticker, side, quantity, price, executed_at}
insert_snapshot(conn, total_value) -> None
get_snapshots(conn, limit=1000) -> list[dict]  # oldest first: {total_value, recorded_at}
get_watchlist(conn) -> list[dict]          # {ticker, added_at}, ordered by added_at
get_watchlist_entry(conn, ticker) -> dict | None
add_watchlist(conn, ticker) -> dict        # idempotent; returns existing entry if present
remove_watchlist(conn, ticker) -> bool     # False if not on the list
insert_chat_message(conn, role, content, actions: dict | None) -> dict
get_chat_messages(conn, limit=50) -> list[dict]  # oldest first; actions decoded from JSON
```

Repo functions do not open transactions; the caller does.

### Services (owner: backend)

```python
# app/portfolio.py
class TradeError(ValueError)     # message is the user-facing error -> HTTP 400
def portfolio_summary(conn, cache) -> dict          # GET /api/portfolio shape, rounded
async def execute_trade(conn, cache, source, ticker, side, quantity) -> dict
    # normalizes ticker, one BEGIN IMMEDIATE transaction, writes snapshot,
    # untracks the ticker if a sell closed a position not on the watchlist.
    # Returns {"trade": {...}, "portfolio": {...}} (POST /api/portfolio/trade shape)

# app/watchlist.py
async def add_ticker(conn, source, cache, ticker) -> dict    # entry {ticker, price, added_at}; ValueError -> 400
async def remove_ticker(conn, source, ticker) -> None        # KeyError if not on list -> 404

# app/snapshots.py
def record_snapshot(conn, cache) -> None
async def snapshot_loop(conn, cache, interval=30.0) -> None
```

### App state (owner: backend)

`app.state.price_cache` (the stream router already reads this name), `app.state.source`, `app.state.db` (one shared sqlite connection).

### LLM (owner: llm)

```python
# app/llm.py
class Trade, WatchlistChange, ChatReply   # exactly as PLAN.md Section 9
class LLMUnavailable(Exception)           # -> HTTP 503
async def get_chat_reply(messages: list[dict]) -> ChatReply   # honours LLM_MOCK=true

# app/chat.py
async def handle_chat(conn, cache, source, message: str) -> dict   # POST /api/chat response shape
def chat_history(conn) -> dict                                     # GET /api/chat response shape

# app/routes/chat.py
router = APIRouter()   # backend includes it in main.py
```

Chat actions call `app.watchlist.add_ticker/remove_ticker` and `app.portfolio.execute_trade`, so manual and LLM actions share one code path.

## Frontend contract

The frontend uses the REST and SSE shapes in PLAN.md Sections 6 and 8 and nothing else. Static export lands in `frontend/out`; the Dockerfile copies it to `/app/static`. For local dev without Docker, the backend serves `../frontend/out` when `/app/static` does not exist (owner: backend).

Stable `data-testid` attributes the tester relies on (frontend keeps these):
`connection-dot` (with `data-state="open|connecting|closed"`), `header-total`, `header-cash`, `watchlist-row-{TICKER}`, `watchlist-price-{TICKER}`, `watchlist-add-input`, `watchlist-add-button`, `watchlist-remove-{TICKER}`, `main-chart`, `trade-ticker`, `trade-quantity`, `trade-buy`, `trade-sell`, `trade-error`, `positions-table`, `position-row-{TICKER}`, `heatmap`, `pnl-chart`, `chat-input`, `chat-send`, `chat-message` (one per message), `chat-loading`, `chat-action` (one per inline action result).

## Status board

Each agent appends one line here when a milestone is done (`- [name] done: ...`).
- [database] done: backend/app/db/ (schema.sql, connection.py, repo.py) per the app.db interface; 17 tests in app/tests/db pass (`uv run pytest app/tests/db`).
- [backend] done: FastAPI app runs end to end (`cd backend && uv run uvicorn app.main:app --port 8000`): portfolio/watchlist/health routes, services, lifespan, static mount; full suite 134 passing (`uv run pytest`; test deps now in the uv dev group, so no `--extra dev`).
- [llm] done: app/llm.py (Router Groq -> OpenRouter free, structured ChatReply, LLM_MOCK), app/chat.py, app/routes/chat.py (POST/GET /api/chat, 503 when LLM unavailable); 20 tests in app/tests/llm pass; live Groq smoke test OK
- [frontend] done: frontend/ Next.js 16 static export (`npm run build` -> frontend/out), Tailwind 4, Lightweight Charts 5, hand-rolled treemap; all TEAM.md data-testids present (plus `heatmap-tile-{TICKER}` with `data-pnl=up|down`, `chat-error`, `chat-message[data-role]`, `chat-action[data-status]`); 18 Vitest tests pass (`npm test`); smoke-tested against the live backend with LLM_MOCK=true.
- [devops] done: Dockerfile, .dockerignore, scripts/*, README Run section; image builds, container verified (/api/health, /, SSE, mock chat) with LLM_MOCK=true
- [tester] done: Playwright E2E suite in test/ (8 tests: fresh start, watchlist add/remove, buy, sell, oversell error, heatmap + P&L chart, heatmap colours, mocked AI chat) passes 8/8 against a fresh Docker container (LLM_MOCK=true, new volume). Run: `cd test && npm ci && npx playwright install chromium && npx playwright test` (BASE_URL overrides http://localhost:8000).
