"use client";

import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { ChatMessage, ChatResponse } from "@/lib/types";
import { ChatActions } from "./ChatActions";

const BUSY = "The assistant is busy, try again in a moment";

export function ChatPanel({ onActions }: { onActions: (reply: ChatResponse) => void }) {
  const [open, setOpen] = useState(true);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.chatHistory().then((r) => setMessages(r.messages)).catch(() => {});
  }, []);

  useEffect(() => { end.current?.scrollIntoView?.({ block: "end" }); }, [messages, loading]);

  const send = async (e: React.FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || loading) return;
    const now = new Date().toISOString();
    setMessages((m) => [...m, { id: `local-${now}`, role: "user", content: text, actions: null, created_at: now }]);
    setInput("");
    setError(null);
    setLoading(true);
    try {
      const reply = await api.sendChat(text);
      const { message, ...actions } = reply;
      setMessages((m) => [...m, { id: `reply-${now}`, role: "assistant", content: message, actions, created_at: new Date().toISOString() }]);
      onActions(reply);
    } catch (err) {
      setError(err instanceof ApiError && err.status === 503 ? BUSY : (err as Error).message);
    } finally {
      setLoading(false);
    }
  };

  if (!open) {
    return (
      <button onClick={() => setOpen(true)} aria-label="Open assistant"
        className="flex w-9 shrink-0 items-start justify-center border-l border-line bg-panel pt-3 text-sm font-semibold text-accent [writing-mode:vertical-rl]">
        Assistant
      </button>
    );
  }

  return (
    <aside className="flex w-[360px] shrink-0 flex-col border-l border-line bg-panel">
      <header className="flex h-8 shrink-0 items-center justify-between border-b border-line px-3">
        <h2 className="text-[13px] font-semibold text-accent [font-stretch:85%]">Assistant</h2>
        <button onClick={() => setOpen(false)} aria-label="Collapse assistant" className="px-1 text-dim hover:text-text">›</button>
      </header>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-3 text-sm">
        {messages.length === 0 && !loading && (
          <p className="text-dim">Ask about your portfolio, or tell me what to trade. For example: &ldquo;Buy 5 NVDA&rdquo; or &ldquo;How concentrated am I?&rdquo;</p>
        )}
        {messages.map((m) => (
          <div key={m.id} data-testid="chat-message" data-role={m.role}
            className={m.role === "user" ? "ml-8 border border-line bg-raised px-3 py-2" : "mr-4 border-l-2 border-blue pl-3"}>
            <p className="whitespace-pre-wrap leading-relaxed">{m.content}</p>
            <ChatActions actions={m.actions} />
          </div>
        ))}
        {loading && (
          <div data-testid="chat-loading" className="flex items-center gap-2 text-dim">
            <span className="h-2 w-2 animate-pulse rounded-full bg-blue" /> Thinking
          </div>
        )}
        {error && <p data-testid="chat-error" role="alert" className="text-down">{error}</p>}
        <div ref={end} />
      </div>
      <form onSubmit={send} className="flex gap-2 border-t border-line p-2">
        <input data-testid="chat-input" aria-label="Message the assistant" value={input} onChange={(e) => setInput(e.target.value)}
          placeholder="Message FinAlly" className="min-w-0 flex-1 border border-line bg-ink px-2 py-1.5 text-sm placeholder:text-dim" />
        <button data-testid="chat-send" type="submit" disabled={loading}
          className="bg-purple px-4 text-sm font-semibold text-white hover:brightness-110 disabled:opacity-50">Send</button>
      </form>
    </aside>
  );
}
