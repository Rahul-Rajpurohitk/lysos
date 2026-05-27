/**
 * chemUtils — tiny client-side chemistry heuristics.
 *
 * These mirror the backend gates (chem_synthesis._non_drug_like_reason,
 * chem_ip._non_drug_like_reason) but run in the browser so STALE saved
 * artifacts that pre-date the backend gates also short-circuit cleanly
 * to the "not applicable" empty state instead of half-rendering.
 */

/** Rough SMILES heavy-atom count + ring detection. Returns a reason
 *  string if the molecule isn't a drug-like candidate, else null.
 *
 *  Not an RDKit replacement — approximate but correct for the cases
 *  that matter here (commodity reagents like acetic anhydride show
 *  ~7 heavy atoms with no ring; real drug candidates clear the bar
 *  easily). */
export function isLikelyNonDrug(smiles: string | null | undefined): string | null {
  if (!smiles) return null;
  // Match atom occurrences:
  //  - [X...]    bracketed atom — symbol after [
  //  - Cl / Br   two-char halogens (must match BEFORE single letters)
  //  - B C N O P S F I   single-letter heavy atoms
  //  - b c n o p s        aromatic lowercase
  // The H atom (or h) is hydrogen → not counted.
  const pat = /\[([A-Za-z][a-z]?)|Cl|Br|[BCNOPSFI]|[bcnops]/g;
  let heavy = 0;
  for (const m of smiles.matchAll(pat)) {
    const atom = m[1] || m[0];
    if (atom !== "H" && atom !== "h") heavy++;
  }
  // Rings: SMILES uses digit pairs (or %NN) as ring-closure markers.
  const hasRing = /[1-9]|%\d{2}/.test(smiles);
  if (heavy < 10) {
    return `only ${heavy} heavy atoms — likely a reagent or fragment, not a drug candidate`;
  }
  if (!hasRing) {
    return "acyclic molecule — no ring system, not a drug-like scaffold";
  }
  return null;
}
