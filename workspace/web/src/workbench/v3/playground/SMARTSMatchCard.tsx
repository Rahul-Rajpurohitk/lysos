/**
 * SMARTSMatchCard — substructure pattern search.
 *
 * Lets the user input ANY SMARTS pattern (or pick from a curated library)
 * and see live which atoms match in the current SMILES. Matched atom indices
 * surface up via onMatchSelected so the 2D builder can highlight them.
 *
 * Curated library: 14 common medchem patterns
 *   - Aromatic / saturated rings
 *   - β-lactam, sulfonamide, peptide bond
 *   - Carbonyl, ester, amide, nitrile
 *   - H-bond donor / acceptor
 *   - Aromatic nitrogen
 *
 * UX:
 *   1. Search box at top + library buttons
 *   2. Match results: atom indices with bond count
 *   3. Click a match → highlight in 2D builder via onMatchSelected
 */
import { useEffect, useState } from "react";
import { Search, Sparkles, RefreshCw } from "lucide-react";

interface SMARTSMatch {
  atom_indices: number[];
  bond_indices: number[];
}

interface MatchResponse {
  smiles: string;
  smarts: string;
  n_matches: number;
  matches: SMARTSMatch[];
  valid_smarts: boolean;
  error: string;
}

interface Props {
  apiBase: string;
  smiles: string | null;
  onMatchSelected?: (match: SMARTSMatch | null) => void;
}

const PRESETS: Array<{ label: string; smarts: string; desc: string }> = [
  { label: "aromatic-N",   smarts: "[n]",                       desc: "any aromatic nitrogen" },
  { label: "carbonyl",     smarts: "[CX3]=[OX1]",               desc: "C=O" },
  { label: "amide",        smarts: "[NX3][CX3](=[OX1])",        desc: "amide bond" },
  { label: "ester",        smarts: "[#6][CX3](=O)O[#6]",        desc: "carboxylic ester" },
  { label: "carboxylic",   smarts: "C(=O)[OH]",                 desc: "free –COOH" },
  { label: "β-lactam",     smarts: "[#7]1[#6](=O)[#6]([#6]1)",  desc: "4-membered β-lactam" },
  { label: "sulfonamide",  smarts: "[#16](=O)(=O)[#7]",         desc: "S(=O)(=O)N" },
  { label: "peptide",      smarts: "[NX3][CX3](=O)[CX3]",       desc: "peptide bond" },
  { label: "nitrile",      smarts: "[#6]#[#7]",                 desc: "C≡N" },
  { label: "nitro",        smarts: "[#7+](=O)[O-]",             desc: "nitro group" },
  { label: "halogen",      smarts: "[F,Cl,Br,I]",               desc: "any halogen" },
  { label: "hbond-donor",  smarts: "[#7,#8;H]",                 desc: "N–H or O–H donor" },
  { label: "hbond-accept", smarts: "[#7,#8;!H0]",               desc: "N or O acceptor" },
  { label: "phenol",       smarts: "c[OH]",                     desc: "aromatic OH" },
];

export function SMARTSMatchCard({ apiBase, smiles, onMatchSelected }: Props) {
  const [smarts, setSmarts] = useState<string>("");
  const [resp, setResp] = useState<MatchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [activeMatch, setActiveMatch] = useState<number>(-1);

  async function runMatch(pattern: string) {
    if (!smiles || !pattern) {
      setResp(null);
      return;
    }
    setLoading(true);
    try {
      const r = await fetch(`${apiBase}/workbench/molecule/smarts-match`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ smiles, smarts: pattern }),
      });
      if (!r.ok) {
        setResp(null);
        return;
      }
      const d: MatchResponse = await r.json();
      setResp(d);
      setActiveMatch(d.matches.length > 0 ? 0 : -1);
      onMatchSelected?.(d.matches.length > 0 ? d.matches[0] : null);
    } catch {
      setResp(null);
    } finally {
      setLoading(false);
    }
  }

  // Re-run on SMILES change if a pattern is set
  useEffect(() => {
    if (smarts) runMatch(smarts);
    /* eslint-disable-next-line react-hooks/exhaustive-deps */
  }, [smiles]);

  function pickPreset(p: { smarts: string; label: string }) {
    setSmarts(p.smarts);
    runMatch(p.smarts);
  }

  function clearMatch() {
    setActiveMatch(-1);
    onMatchSelected?.(null);
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
        <Search size={11} style={{ color: "#0891b2" }} />
        <span>smarts · {resp ? `${resp.n_matches} match${resp.n_matches !== 1 ? "es" : ""}` : "pattern search"}</span>
        <span style={{ flex: 1 }} />
        <button type="button" onClick={() => smarts && runMatch(smarts)} disabled={loading}
          style={{ border: 0, background: "transparent", cursor: loading ? "wait" : "pointer", padding: 2, color: "var(--lys-text-faint)" }}>
          <RefreshCw size={11} />
        </button>
      </div>

      {/* Input + preset chips */}
      <div style={{ padding: "6px 8px", display: "flex", flexDirection: "column", gap: 4 }}>
        <div style={{ display: "flex", gap: 4 }}>
          <input
            type="text"
            value={smarts}
            onChange={(e) => setSmarts(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") runMatch(smarts); }}
            placeholder="SMARTS pattern · e.g. c1ccccc1"
            disabled={!smiles}
            style={{
              flex: 1, fontSize: 11, fontFamily: "var(--lys-font-mono)",
              padding: "3px 6px", borderRadius: 4,
              border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.08))",
              background: "var(--lys-bg-1, #ffffff)",
              color: "var(--lys-text)",
              outline: "none",
            }}
          />
          <button type="button" onClick={() => runMatch(smarts)} disabled={!smiles || !smarts}
            style={{
              padding: "3px 10px", borderRadius: 4, fontSize: 10,
              fontFamily: "var(--lys-font-mono)", fontWeight: 600,
              background: "#0891b2", color: "white",
              border: 0, cursor: smiles && smarts ? "pointer" : "not-allowed",
              opacity: smiles && smarts ? 1 : 0.5,
            }}>match</button>
        </div>

        {/* Preset chips */}
        <div style={{ display: "flex", flexWrap: "wrap", gap: 3 }}>
          {PRESETS.map((p) => (
            <button
              key={p.label} type="button" title={`${p.smarts} · ${p.desc}`}
              onClick={() => pickPreset(p)}
              disabled={!smiles}
              style={{
                padding: "1px 6px", borderRadius: 999, fontSize: 9,
                fontFamily: "var(--lys-font-mono)",
                border: "1px solid var(--lys-border-faint, rgba(0,0,0,0.08))",
                background: smarts === p.smarts ? "rgba(8,145,178,0.10)" : "var(--lys-bg-3, rgba(0,0,0,0.02))",
                color: smarts === p.smarts ? "#0891b2" : "var(--lys-text-dim)",
                cursor: smiles ? "pointer" : "not-allowed",
                opacity: smiles ? 1 : 0.5,
              }}>{p.label}</button>
          ))}
        </div>
      </div>

      {/* Results */}
      <div style={{ flex: 1, overflow: "auto", padding: "0 8px 8px 8px" }}>
        {!smiles && (
          <div style={{ color: "var(--lys-text-faint)", fontSize: 10.5,
            padding: "20px 10px", textAlign: "center",
            fontFamily: "var(--lys-font-mono)" }}>
            no candidate yet · pick a scaffold first
          </div>
        )}
        {smiles && resp && !resp.valid_smarts && (
          <div style={{ color: "#dc2626", fontSize: 10, padding: 8,
            background: "rgba(220,38,38,0.08)", borderRadius: 4,
            fontFamily: "var(--lys-font-mono)" }}>
            invalid SMARTS: {resp.error || resp.smarts}
          </div>
        )}
        {smiles && resp && resp.valid_smarts && resp.n_matches === 0 && (
          <div style={{ color: "var(--lys-text-faint)", fontSize: 10.5,
            padding: "8px 6px", textAlign: "center",
            fontFamily: "var(--lys-font-mono)" }}>
            no matches · pattern not found in candidate
          </div>
        )}
        {smiles && resp && resp.valid_smarts && resp.matches.length > 0 && (
          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            {resp.matches.map((m, i) => {
              const active = i === activeMatch;
              return (
                <button
                  key={i} type="button"
                  onClick={() => {
                    setActiveMatch(active ? -1 : i);
                    onMatchSelected?.(active ? null : m);
                  }}
                  style={{
                    textAlign: "left", padding: "4px 8px",
                    borderRadius: 4, fontSize: 10,
                    fontFamily: "var(--lys-font-mono)",
                    border: `1px solid ${active ? "#0891b2" : "var(--lys-border-faint, rgba(0,0,0,0.08))"}`,
                    background: active ? "rgba(8,145,178,0.10)" : "var(--lys-bg-3, rgba(0,0,0,0.02))",
                    color: "var(--lys-text)",
                    cursor: "pointer",
                    display: "flex", alignItems: "center", gap: 6,
                  }}>
                  <Sparkles size={10} style={{ color: active ? "#0891b2" : "var(--lys-text-faint)" }} />
                  <span>match #{i + 1}</span>
                  <span style={{ color: "var(--lys-text-faint)", fontSize: 9 }}>·</span>
                  <span style={{ color: "#0891b2", fontWeight: 600 }}>{m.atom_indices.length} atoms</span>
                  <span style={{ color: "var(--lys-text-faint)", fontSize: 9 }}>
                    [{m.atom_indices.slice(0, 6).join(",")}{m.atom_indices.length > 6 ? "…" : ""}]
                  </span>
                </button>
              );
            })}
            {activeMatch >= 0 && (
              <button type="button" onClick={clearMatch}
                style={{
                  marginTop: 4, fontSize: 9, padding: "2px 8px",
                  fontFamily: "var(--lys-font-mono)",
                  border: "1px dashed var(--lys-border-faint, rgba(0,0,0,0.15))",
                  background: "transparent", color: "var(--lys-text-faint)",
                  borderRadius: 4, cursor: "pointer",
                }}>clear highlight</button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
