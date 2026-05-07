/**
 * SMILES-keyed cache for /molecule/state responses.
 *
 * Multiple components in the chem container want the same per-molecule
 * data (diagnostics, bonds, properties, auto_patterns, match_known) on
 * the same SMILES change. Without coordination they all fire their own
 * fetches → backend parses RDKit N times for one user edit. This module
 * provides:
 *
 *   - getMoleculeState(apiBase, smiles, includes)
 *       Returns cached data if a recent (≤5s) entry exists for the
 *       same (smiles, includes) combo. Otherwise fetches and caches.
 *       Concurrent requests for the same key dedupe to one in-flight
 *       promise — second caller awaits the first.
 *
 *   - invalidate(smiles?)
 *       Drops cache for one SMILES (or everything if no arg). Called
 *       from the WS subscription on `molecule.edit` events so the
 *       agent's in-flight changes don't return stale data.
 *
 *   - subscribe(smiles, fn) / publish(smiles, data)
 *       Lightweight event bus so components listening on a SMILES key
 *       are notified when its cache entry changes. Used by the agent-
 *       driven WS path: fetch → invalidate → re-fetch → publish.
 */

export interface MoleculeStatePayload {
  smiles: string;
  n_atoms: number;
  n_bonds: number;
  diagnostics?: any;
  bonds?: { bonds: any[]; n_bonds: number };
  auto_patterns?: { matches: any[]; count: number; total_presets_checked: number };
  match_known?: { matches: any[]; best: any; is_known: boolean };
  properties?: any;
}

interface CacheEntry {
  ts: number;
  data: MoleculeStatePayload;
}

const TTL_MS = 5000; // 5s freshness window
const cache = new Map<string, CacheEntry>();
const inflight = new Map<string, Promise<MoleculeStatePayload | null>>();
const subscribers = new Map<string, Set<(d: MoleculeStatePayload) => void>>();

function cacheKey(smiles: string, includes: string): string {
  return `${smiles}|${includes}`;
}

export async function getMoleculeState(
  apiBase: string,
  smiles: string,
  includes: string = "diagnostics,bonds,auto_patterns,match_known,properties",
  opts: { force?: boolean; topK?: number } = {}
): Promise<MoleculeStatePayload | null> {
  if (!smiles) return null;
  const key = cacheKey(smiles, includes);
  const now = Date.now();
  const hit = cache.get(key);
  if (!opts.force && hit && (now - hit.ts) < TTL_MS) {
    return hit.data;
  }
  // Coalesce concurrent requests for the same key
  const existing = inflight.get(key);
  if (existing && !opts.force) return existing;
  const promise = (async (): Promise<MoleculeStatePayload | null> => {
    try {
      const url = `${apiBase}/workbench/molecule/state?smiles=${encodeURIComponent(smiles)}&include=${encodeURIComponent(includes)}&top_k=${opts.topK ?? 3}`;
      const r = await fetch(url);
      if (!r.ok) return null;
      const d = await r.json();
      cache.set(key, { ts: Date.now(), data: d });
      // Notify subscribers
      const subs = subscribers.get(smiles);
      if (subs) subs.forEach((fn) => { try { fn(d); } catch {/*noop*/} });
      return d;
    } catch {
      return null;
    } finally {
      inflight.delete(key);
    }
  })();
  inflight.set(key, promise);
  return promise;
}

export function invalidate(smiles?: string): void {
  if (!smiles) {
    cache.clear();
    return;
  }
  // Drop every cache entry whose key starts with this smiles
  const prefix = smiles + "|";
  for (const k of cache.keys()) {
    if (k.startsWith(prefix)) cache.delete(k);
  }
}

export function subscribe(smiles: string, fn: (d: MoleculeStatePayload) => void): () => void {
  let set = subscribers.get(smiles);
  if (!set) { set = new Set(); subscribers.set(smiles, set); }
  set.add(fn);
  return () => {
    const s = subscribers.get(smiles);
    if (s) {
      s.delete(fn);
      if (s.size === 0) subscribers.delete(smiles);
    }
  };
}

export function publish(smiles: string, data: MoleculeStatePayload): void {
  cache.set(cacheKey(smiles, "diagnostics,bonds,auto_patterns,match_known,properties"), { ts: Date.now(), data });
  const subs = subscribers.get(smiles);
  if (subs) subs.forEach((fn) => { try { fn(data); } catch {/*noop*/} });
}

// Debug / testing
export function _cacheStats() {
  return { size: cache.size, inflight: inflight.size, subscribers: subscribers.size };
}
