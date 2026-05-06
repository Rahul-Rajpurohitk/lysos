/**
 * useAutoTitle — auto-summarize a chat tab into a 3-6 word title.
 *
 * Strategy:
 *  • Watch the active tab's events. After the user has sent ≥1 message
 *    AND there have been ≥3 events since the last summarization, fire
 *    POST /api/chat/title. The endpoint reads the Orchestrator ledger
 *    server-side and asks the LLM for a tight label.
 *  • Debounced — we only re-summarize every 3 events to keep LLM calls
 *    cheap, and only when the active tab is currently being typed in.
 *  • Skipped when `userRenamed` is true — once a human types a name,
 *    the auto-summarizer leaves it alone forever.
 *  • Uniqueness: ensureUniqueTitle() appends "(2)", "(3)", … if the
 *    proposed title collides with another tab in the same project.
 *  • Many tabs: each tab has its own counter ref; only the active tab
 *    gets watched (cheap). Background tabs keep their stale title until
 *    next focus.
 */
import { useEffect, useRef } from "react";

export interface AutoTitleParams {
  apiBase: string;
  chatId: string;
  eventCount: number;
  hasUserMessage: boolean;
  isActive: boolean;
  userRenamed: boolean;
  takenTitles: string[];          // titles in use across the other tabs
  onTitle: (title: string) => void;
}

export function useAutoTitle(p: AutoTitleParams) {
  // Per-chat-id ref of the event count at which we last summarized.
  // (Survives unmount within the same React tree via WeakMap-by-id pattern.)
  const lastByIdRef = useRef<Record<string, number>>({});

  useEffect(() => {
    if (!p.isActive) return;
    if (p.userRenamed) return;
    if (!p.hasUserMessage) return;

    const lastN = lastByIdRef.current[p.chatId] ?? 0;
    if (p.eventCount - lastN < 3) return;

    // Debounce — wait 600ms of quiet before firing
    const ctrl = new AbortController();
    const timer = setTimeout(async () => {
      lastByIdRef.current[p.chatId] = p.eventCount;
      try {
        const r = await fetch(`${p.apiBase}/api/chat/title`, {
          method: "POST",
          signal: ctrl.signal,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ session_id: p.chatId }),
        });
        if (!r.ok) return;
        const d = await r.json();
        const raw = (d.title ?? "").trim();
        if (!raw) return;
        const unique = ensureUniqueTitle(raw, p.takenTitles);
        p.onTitle(unique);
      } catch {
        /* swallow — abort or transient */
      }
    }, 600);

    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [p.chatId, p.eventCount, p.isActive, p.userRenamed, p.hasUserMessage,
      p.takenTitles.join("|"), p.apiBase]);
}

/** If `title` collides with an existing tab title, append "(2)", "(3)", …
 *  Case-insensitive comparison so "Macrolide for MRSA" and "macrolide for mrsa"
 *  count as duplicates. */
export function ensureUniqueTitle(title: string, taken: string[]): string {
  const lc = (s: string) => s.trim().toLowerCase();
  const base = lc(title);
  if (!taken.some((t) => lc(t) === base)) return title;
  for (let n = 2; n < 999; n++) {
    const cand = `${title} (${n})`;
    if (!taken.some((t) => lc(t) === lc(cand))) return cand;
  }
  return title;
}
