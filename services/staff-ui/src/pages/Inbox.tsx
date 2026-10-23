/**
 * WhatsApp takeover screen (ACS has no staff inbox).
 *
 * Shows conversations the bot handed over (emergencies first), the message
 * history, and lets front-office staff take over, reply and hand back.
 */
import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { config } from "../config";
import type { ChatMessage, Conversation } from "../types";

const REASON_LABELS: Record<string, string> = {
  emergency: "🚨 Emergency",
  self_harm: "🚨 Crisis",
  low_confidence: "Unclear question",
  no_answer: "No answer found",
  requested: "Asked for staff",
  llm_unavailable: "AI unavailable",
  safety_unavailable: "Safety check unavailable",
};

export function Inbox() {
  const [filter, setFilter] = useState<"waiting" | "mine" | "all">("waiting");
  const [items, setItems] = useState<Conversation[]>([]);
  const [selected, setSelected] = useState<Conversation | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [draft, setDraft] = useState("");
  const [notice, setNotice] = useState("");

  const refresh = useCallback(async () => {
    setItems(await api.conversations(filter));
    if (selected) setMessages(await api.messages(selected.id));
  }, [filter, selected]);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), config.pollSeconds * 1000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const open = async (conversation: Conversation) => {
    setSelected(conversation);
    setNotice("");
    setMessages(await api.messages(conversation.id));
  };

  const act = async (action: () => Promise<Conversation>) => {
    const updated = await action();
    setSelected({ ...selected!, ...updated });
    await refresh();
  };

  const send = async () => {
    if (!selected || !draft.trim()) return;
    try {
      const result = await api.reply(selected.id, draft.trim());
      setNotice(result.status === "failed" ? `Not delivered: ${result.error}` : "");
      setDraft("");
      await refresh();
    } catch (e) {
      setNotice((e as Error).message);
    }
  };

  return (
    <div className="split">
      <section className="list">
        <div className="toolbar">
          {(["waiting", "mine", "all"] as const).map((f) => (
            <button key={f} className={f === filter ? "active" : ""} onClick={() => setFilter(f)}>
              {f === "waiting" ? "Waiting" : f === "mine" ? "Mine" : "All"}
            </button>
          ))}
        </div>
        {items.length === 0 && <p className="muted">No conversations.</p>}
        {items.map((c) => (
          <button key={c.id} className={`row ${selected?.id === c.id ? "active" : ""}`} onClick={() => void open(c)}>
            <span>
              <strong>{c.patient_name ?? c.phone}</strong>
              <small className="muted"> {c.language.toUpperCase()}</small>
            </span>
            <span className={c.handover_reason === "emergency" || c.handover_reason === "self_harm" ? "badge danger" : "badge"}>
              {REASON_LABELS[c.handover_reason ?? ""] ?? c.status}
            </span>
          </button>
        ))}
      </section>

      <section className="chat">
        {!selected && <p className="muted">Select a conversation.</p>}
        {selected && (
          <>
            <div className="toolbar">
              <strong>{selected.patient_name ?? "Unknown patient"}</strong>
              <a href={`tel:${selected.phone}`}>{selected.phone}</a>
              {selected.status !== "human" && <button onClick={() => void act(() => api.takeover(selected.id))}>Take over</button>}
              <button onClick={() => void act(() => api.release(selected.id))}>Hand back to bot</button>
            </div>
            <ol className="messages">
              {messages.map((m) => (
                <li key={m.id} className={m.direction}>
                  <span className="who">{m.sender}</span>
                  <p>{m.body}</p>
                  <time>{new Date(m.created_at).toLocaleString()}</time>
                </li>
              ))}
            </ol>
            {!selected.session_open && (
              <p className="warning">The 24-hour WhatsApp window has closed – call the patient or wait for them to write.</p>
            )}
            {notice && <p className="warning">{notice}</p>}
            <div className="composer">
              <textarea value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Type a reply…" rows={3} />
              <button onClick={() => void send()} disabled={!draft.trim()}>
                Send
              </button>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
