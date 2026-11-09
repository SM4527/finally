import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ChatPanel } from "@/components/ChatPanel";

const history = {
  messages: [
    { id: "1", role: "user", content: "Hi", actions: null, created_at: "" },
    { id: "2", role: "assistant", content: "Hello", actions: { watchlist_changes: [], trades: [] }, created_at: "" },
  ],
};

const reply = {
  message: "Bought 1 AAPL",
  watchlist_changes: [{ ticker: "PYPL", action: "add", status: "ok", error: null }],
  trades: [
    { ticker: "AAPL", side: "buy", quantity: 1, status: "ok", price: 190.5, error: null },
    { ticker: "TSLA", side: "sell", quantity: 5, status: "error", price: null, error: "No position" },
  ],
};

function stubFetch(chatResponse: () => Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn((_url: string, init?: RequestInit) =>
    init?.method === "POST" ? chatResponse() : Promise.resolve(Response.json(history))));
}

afterEach(() => vi.unstubAllGlobals());

describe("ChatPanel", () => {
  it("loads history on mount", async () => {
    stubFetch(async () => Response.json(reply));
    render(<ChatPanel onActions={() => {}} />);
    expect(await screen.findAllByTestId("chat-message")).toHaveLength(2);
  });

  it("shows loading, then the reply with inline actions", async () => {
    let resolve!: (r: Response) => void;
    stubFetch(() => new Promise((r) => { resolve = r; }));
    const onActions = vi.fn();
    const user = userEvent.setup();
    render(<ChatPanel onActions={onActions} />);
    await screen.findAllByTestId("chat-message");
    await user.type(screen.getByTestId("chat-input"), "buy apple");
    await user.click(screen.getByTestId("chat-send"));
    expect(screen.getByTestId("chat-loading")).toBeInTheDocument();
    resolve(Response.json(reply));
    expect(await screen.findByText("Bought 1 AAPL")).toBeInTheDocument();
    expect(screen.queryByTestId("chat-loading")).not.toBeInTheDocument();
    const actions = screen.getAllByTestId("chat-action");
    expect(actions.map((a) => a.textContent)).toEqual([
      "Added PYPL to watchlist",
      "Bought 1 AAPL at $190.50",
      "Failed to sell 5 TSLA: No position",
    ]);
    expect(actions[2]).toHaveAttribute("data-status", "error");
    expect(onActions).toHaveBeenCalledOnce();
  });

  it("shows the busy message on 503", async () => {
    stubFetch(async () => Response.json({ detail: "LLM unavailable" }, { status: 503 }));
    const user = userEvent.setup();
    render(<ChatPanel onActions={() => {}} />);
    await user.type(screen.getByTestId("chat-input"), "hello");
    await user.click(screen.getByTestId("chat-send"));
    expect(await screen.findByTestId("chat-error")).toHaveTextContent("The assistant is busy, try again in a moment");
  });
});
