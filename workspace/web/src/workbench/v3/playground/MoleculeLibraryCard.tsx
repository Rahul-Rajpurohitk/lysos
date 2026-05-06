/**
 * MoleculeLibraryCard — persistent CRUD library of saved molecules.
 *
 * Backed by /workbench/library/molecules (SQLite, survives restarts).
 *
 * Features:
 *   - List all saved molecules with QED, MW, Lipinski-pass tile
 *   - Filter chips for distinct tags (driven by /library/tags)
 *   - Substring search across name/note/SMILES
 *   - Save the CURRENT candidate (with name + tag input)
 *   - Click any entry → loadSmilesIntoCanvas (live the molecule)
 *   - Delete entry (× button)
 *   - Auto-refresh when filters change
 *
 * This is what makes the workbench feel like a real lab notebook —
 * you can build up a library of leads across sessions.
 */
import { useEffect, useState } from "react";
import { Library, RefreshCw, Plus, X, Search } from "lucide-react";

interface LibraryEntry {
  id: number;
  smiles: string;
  canonical_smiles: string;
  inchi_key: string;
  name: string;
  tags: string[];
  note: string;
  qed: number;
  mw: number;
  logp: number;
  tpsa: number;
  n_heavy_atoms: number;
  lipinski_pass: boolean;
  created_at: number;
  updated_at: number;
}

interface TagInfo {
  tag: string;
  count: number;
}

interface Props {
  apiBase: string;
  currentSmiles: string | null;
  onLoad?: (smiles: string, name: string) => void;
}

export function MoleculeLibraryCard({ apiBase, currentSmiles, onLoad }: Props) {
  const [entries, setEntries] = useState<LibraryEntry[]>([]);
  const [tags, setTags] = useState<TagInfo[]>([]);
  const [activeTag, setActiveTag] = useState<string>("");
  const [query, setQuery] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [showSave, setShowSave] = useState(false);
  const [saveName, setSaveName] = useState("");
  const [saveTags, setSaveTags] = useState("");
  const [saveNote, setSaveNote] = useState("");

  async function refresh() {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (activeTag) params.set("tag", activeTag);
      if (query) params.set("q", query);
      const r = await fetch(`${apiBase}/workbench/library/molecules?${params.toString()}`);
      if (!r.ok) return;
      const d = await r.json();
      setEntries(d.entries ?? []);
    } finally {
      setLoading(false);
    }
    try {
      const r2 = await fetch(`${apiBase}/workbench/library/tags`);
      if (r2.ok) {
        const d2 = await r2.json();
        setTags(d2.tags ?? []);
      }
    } catch {/*noop*/}
  }
  useEffect(() => { refresh(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [activeTag, query, apiBase]);

  async function saveCurrent() {
    if (!currentSmiles) return;
    const tagsArr = saveTags.split(",").map((t) => t.trim()).filter(Boolean);
    try {
      const r = await fetch(`${apiBase}/workbench/library/molecules`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          smiles: currentSmiles,
          name: saveName || "(unnamed)",
          tags: tagsArr,
          note: saveNote,
        }),
      });
      if (!r.ok) return;
      setShowSave(false);
      setSaveName("");
      setSaveTags("");
      setSaveNote("");
      refresh();
    } catch {/*noop*/}
  }

  async function deleteEntry(id: number) {
    try {
      await fetch(`${apiBase}/workbench/library/molecules/${id}`, { method: "DELETE" });
      refresh();
    } catch {/*noop*/}
  }

  return (
    <div style={{
      width: "100%", height: "100%", display: "flex", flexDirection: "column",
      background: "var(--lys-bg-2, #ffffff)", overflow: "hidden",
    }}>
      <div style={{
        padding: "5px 10px",
        fontSize: 9.5, fontFamily: "var(--lys-font-mono)",
        color: "var(--lys-text-faint)", letterSpacing: "0.06em",
        textTransform: "uppercase",
        borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
        display: "flex", alignItems: "center", gap: 6,
      }}>
        <Library size={11} style={{ color: "#10b981" }} />
        <span>library · {entries.length} mol{entries.length !== 1 ? "s" : ""}{activeTag && ` · #${activeTag}`}</span>
        <span style={{ flex: 1 }} />
        {currentSmiles && (
          <button type="button" onClick={() => setShowSave(true)} title="Save current candidate"
            style={{ border: 0, background: "transparent", cursor: "pointer", padding: 2, color: "#10b981" }}>
            <Plus size={11} />
          </button>
        )}
        <button type="button" onClick={refresh} disabled={loading}
          style={{ border: 0, background: "transparent", cursor: loading ? "wait" : "pointer", padding: 2, color: "var(--lys-text-faint)" }}>
          <RefreshCw size={11} />
        </button>
      </div>

      {/* Save form (collapsible) */}
      {showSave && currentSmiles && (
        <div style={{
          padding: "6px 8px", display: "flex", flexDirection: "column", gap: 3,
          borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
          background: "rgba(16,185,129,0.05)",
        }}>
          <input type="text" value={saveName} onChange={(e) => setSaveName(e.target.value)}
            placeholder="name · e.g. compound-42 (optional)"
            style={inputStyle} />
          <input type="text" value={saveTags} onChange={(e) => setSaveTags(e.target.value)}
            placeholder="tags · comma-separated (e.g. mrsa, lead, beta-lactam)"
            style={inputStyle} />
          <input type="text" value={saveNote} onChange={(e) => setSaveNote(e.target.value)}
            placeholder="note · why is this interesting?"
            style={inputStyle} />
          <div style={{ display: "flex", gap: 4 }}>
            <button type="button" onClick={saveCurrent}
              style={{
                flex: 1, padding: "3px 8px", borderRadius: 4, fontSize: 10,
                fontFamily: "var(--lys-font-mono)", fontWeight: 600,
                background: "#10b981", color: "white", border: 0, cursor: "pointer",
              }}>save</button>
            <button type="button" onClick={() => setShowSave(false)}
              style={{
                padding: "3px 8px", borderRadius: 4, fontSize: 10,
                fontFamily: "var(--lys-font-mono)",
                background: "transparent", color: "var(--lys-text-faint)",
                border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.08))", cursor: "pointer",
              }}>cancel</button>
          </div>
          <div style={{ fontSize: 9, color: "var(--lys-text-faint)", fontFamily: "var(--lys-font-mono)", wordBreak: "break-all" }}>
            SMILES · {currentSmiles}
          </div>
        </div>
      )}

      {/* Search + tag filters */}
      <div style={{
        padding: "5px 8px", display: "flex", flexDirection: "column", gap: 4,
        borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.04))",
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
          <Search size={10} style={{ color: "var(--lys-text-faint)" }} />
          <input type="text" value={query} onChange={(e) => setQuery(e.target.value)}
            placeholder="search · name, note, SMILES"
            style={{ ...inputStyle, flex: 1 }} />
        </div>
        {tags.length > 0 && (
          <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
            <button type="button" onClick={() => setActiveTag("")}
              style={tagChipStyle(activeTag === "")}>all · {entries.length}</button>
            {tags.map((t) => (
              <button key={t.tag} type="button" onClick={() => setActiveTag(t.tag === activeTag ? "" : t.tag)}
                style={tagChipStyle(t.tag === activeTag)}>{t.tag} · {t.count}</button>
            ))}
          </div>
        )}
      </div>

      {/* Entry list */}
      <div style={{ flex: 1, overflow: "auto" }}>
        {entries.length === 0 && !loading && (
          <div style={{ padding: "20px 10px", textAlign: "center",
            color: "var(--lys-text-faint)", fontSize: 10.5,
            fontFamily: "var(--lys-font-mono)" }}>
            {query || activeTag
              ? "no matches"
              : "library empty · save the current candidate with +"}
          </div>
        )}
        {entries.map((e) => (
          <div key={e.id} style={{
            display: "flex", flexDirection: "column", gap: 2,
            padding: "5px 8px",
            borderBottom: "1px solid var(--lys-border-faint, rgba(0,0,0,0.03))",
            borderLeft: e.lipinski_pass ? "3px solid #10b981" : "3px solid #d97706",
            cursor: onLoad ? "pointer" : "default",
            background: "var(--lys-bg-2, #ffffff)",
          }}
          onClick={() => onLoad?.(e.smiles, e.name)}
          onMouseOver={(ev) => { (ev.currentTarget as HTMLElement).style.background = "var(--lys-bg-3, rgba(0,0,0,0.02))"; }}
          onMouseOut={(ev) => { (ev.currentTarget as HTMLElement).style.background = "var(--lys-bg-2, #ffffff)"; }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ fontSize: 11, fontWeight: 700, color: "var(--lys-text)",
                fontFamily: "var(--lys-font-mono)" }}>
                {e.name || `#${e.id}`}
              </span>
              <span style={{ flex: 1 }} />
              <span style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
                color: "var(--lys-text-faint)" }}>
                QED <span style={{ color: e.qed >= 0.67 ? "#10b981" : e.qed >= 0.4 ? "#d97706" : "#dc2626", fontWeight: 700 }}>
                  {e.qed.toFixed(2)}
                </span>
              </span>
              <span style={{ fontSize: 9, fontFamily: "var(--lys-font-mono)",
                color: "var(--lys-text-faint)" }}>
                MW {e.mw.toFixed(0)}
              </span>
              <button type="button" onClick={(ev) => { ev.stopPropagation(); deleteEntry(e.id); }}
                style={{ border: 0, background: "transparent", cursor: "pointer",
                  padding: 1, color: "#dc2626", opacity: 0.5 }}
                onMouseOver={(ev) => { (ev.currentTarget as HTMLElement).style.opacity = "1"; }}
                onMouseOut={(ev) => { (ev.currentTarget as HTMLElement).style.opacity = "0.5"; }}
                title="Delete">
                <X size={10} />
              </button>
            </div>
            {(e.tags.length > 0 || e.note) && (
              <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
                {e.tags.map((t) => (
                  <span key={t} style={{
                    fontSize: 8.5, padding: "0px 5px", borderRadius: 999,
                    background: "rgba(16,185,129,0.10)", color: "#10b981",
                    fontFamily: "var(--lys-font-mono)",
                  }}>{t}</span>
                ))}
                {e.note && (
                  <span style={{ fontSize: 9, color: "var(--lys-text-dim)",
                    fontFamily: "var(--lys-font-mono)", fontStyle: "italic" }}>
                    {e.note}
                  </span>
                )}
              </div>
            )}
            <div style={{ fontSize: 9, color: "var(--lys-text-faint)",
              fontFamily: "var(--lys-font-mono)", wordBreak: "break-all" }}>
              {e.canonical_smiles.length > 60 ? e.canonical_smiles.slice(0, 57) + "…" : e.canonical_smiles}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  fontSize: 10, fontFamily: "var(--lys-font-mono)",
  padding: "2px 6px", borderRadius: 4,
  border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.08))",
  background: "var(--lys-bg-1, #ffffff)",
  color: "var(--lys-text)",
  outline: "none",
};

function tagChipStyle(active: boolean): React.CSSProperties {
  return {
    padding: "1px 6px", borderRadius: 999, fontSize: 9,
    fontFamily: "var(--lys-font-mono)",
    border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.08))",
    background: active ? "rgba(16,185,129,0.15)" : "var(--lys-bg-3, rgba(0,0,0,0.02))",
    color: active ? "#10b981" : "var(--lys-text-dim)",
    cursor: "pointer",
    fontWeight: active ? 700 : 400,
  };
}
