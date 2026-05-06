/**
 * ChatTabsBar — Claude.ai-style multi-chat tabs for the workbench.
 *
 * Each tab is an independent chat session within the same project: its
 * own events array, slash-command history, design-session subscriptions.
 * Switching tabs is free (no server roundtrip) — events are kept in the
 * parent's `chatEventsBySid` map.
 *
 * Layout: scrollable tab row with an underline-on-active treatment, x to
 * close (visible on hover), + at the end to spawn a new chat.
 */
import { useState } from "react";
import { Plus, X } from "lucide-react";

export interface ChatTab {
  id: string;        // chat session id (chat-<uuid8>)
  title: string;     // user-readable label; auto-generated from first msg
  msgCount: number;  // total events in this tab (for empty-tab indicator)
}

interface ChatTabsBarProps {
  tabs: ChatTab[];
  activeId: string;
  onSelect: (id: string) => void;
  onClose: (id: string) => void;
  onCreate: () => void;
  onRename?: (id: string, title: string) => void;
}

export function ChatTabsBar({ tabs, activeId, onSelect, onClose, onCreate, onRename }: ChatTabsBarProps) {
  return (
    <div
      className="lys-chat-tabs"
      style={{
        display: "flex",
        alignItems: "stretch",
        gap: 0,
        height: 30,
        flexShrink: 0,
        padding: "0 6px",
        borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
        overflowX: "auto",
        overflowY: "hidden",
        scrollbarWidth: "thin",
      }}
    >
      {tabs.map((t) => (
        <ChatTabPill
          key={t.id}
          tab={t}
          active={t.id === activeId}
          canClose={tabs.length > 1}
          onSelect={() => onSelect(t.id)}
          onClose={() => onClose(t.id)}
          onRename={onRename ? (title) => onRename(t.id, title) : undefined}
        />
      ))}
      <button
        type="button"
        onClick={onCreate}
        title="New chat (⌘N)"
        style={{
          display: "grid",
          placeItems: "center",
          width: 28,
          height: 28,
          alignSelf: "center",
          marginLeft: 4,
          border: 0,
          background: "transparent",
          color: "var(--lys-text-faint)",
          borderRadius: 6,
          cursor: "pointer",
          flexShrink: 0,
          transition: "background 0.12s, color 0.12s",
        }}
        onMouseEnter={(e) => {
          e.currentTarget.style.background = "var(--lys-bg-hover, rgba(0,0,0,0.05))";
          e.currentTarget.style.color = "var(--lys-text)";
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.background = "transparent";
          e.currentTarget.style.color = "var(--lys-text-faint)";
        }}
      >
        <Plus size={14} />
      </button>
    </div>
  );
}

interface ChatTabPillProps {
  tab: ChatTab;
  active: boolean;
  canClose: boolean;
  onSelect: () => void;
  onClose: () => void;
  onRename?: (title: string) => void;
}

function ChatTabPill({ tab, active, canClose, onSelect, onClose, onRename }: ChatTabPillProps) {
  const [hover, setHover] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(tab.title);

  function commitRename() {
    setEditing(false);
    const next = draft.trim();
    if (next && next !== tab.title) onRename?.(next);
    else setDraft(tab.title);
  }

  return (
    <div
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      onClick={() => !editing && onSelect()}
      onDoubleClick={() => onRename && setEditing(true)}
      style={{
        position: "relative",
        display: "flex",
        alignItems: "center",
        gap: 6,
        padding: "0 10px",
        height: 30,
        cursor: editing ? "text" : "pointer",
        color: active ? "var(--lys-text)" : "var(--lys-text-dim)",
        fontSize: 12,
        fontWeight: active ? 500 : 400,
        whiteSpace: "nowrap",
        flexShrink: 0,
        // Active tab gets a bottom underline (Claude.ai style)
        borderBottom: active ? "2px solid var(--lys-text)" : "2px solid transparent",
        transition: "color 0.12s, border-bottom-color 0.12s",
      }}
    >
      {editing ? (
        <input
          autoFocus
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commitRename}
          onKeyDown={(e) => {
            if (e.key === "Enter") commitRename();
            if (e.key === "Escape") { setEditing(false); setDraft(tab.title); }
          }}
          style={{
            border: 0,
            outline: 0,
            background: "transparent",
            font: "inherit",
            color: "inherit",
            width: Math.max(80, draft.length * 7),
            padding: 0,
          }}
        />
      ) : (
        <span style={{
          maxWidth: 160,
          overflow: "hidden",
          textOverflow: "ellipsis",
          whiteSpace: "nowrap",
        }}>
          {tab.title || "New chat"}
        </span>
      )}
      {tab.msgCount > 0 && (
        <span style={{
          fontSize: 9.5,
          fontFamily: "var(--lys-font-mono)",
          color: "var(--lys-text-faint)",
          paddingLeft: 2,
        }}>
          {tab.msgCount}
        </span>
      )}
      {canClose && hover && !editing && (
        <button
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            onClose();
          }}
          title="Close chat"
          style={{
            display: "grid",
            placeItems: "center",
            width: 16,
            height: 16,
            border: 0,
            background: "transparent",
            color: "var(--lys-text-faint)",
            borderRadius: 4,
            cursor: "pointer",
            marginLeft: 2,
          }}
          onMouseEnter={(e) => (e.currentTarget.style.background = "rgba(0,0,0,0.06)")}
          onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
        >
          <X size={11} />
        </button>
      )}
    </div>
  );
}
