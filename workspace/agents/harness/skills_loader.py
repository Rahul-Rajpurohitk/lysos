"""SkillsLoader — dynamic context assembler for the agent.

Pattern: ported from atikan-agentic-module/src/orchestrator/skills_loader.py.
Adapted for Lysos: chemistry/AMR domain detection, drug-name entity
detection (218-drug pharma_lookup), token-budget-aware assembly.

Architecture:
    Reads config/skills/*.md tagged with frontmatter:
        ---
        slug: <id>
        loaded: always | loaded_when: <regex/keyword spec>
        ---
    Then for each request:
    1. Always load `core/*` files.
    2. Match `domains/*` files against the user input.
    3. Match `scenarios/*` files against the user intent.
    4. Match `entities/*` files against named drugs / pathogens / PDBs.
    5. Concatenate within a token budget (max_context_tokens).

The output goes into the system prompt of the LLM call so the model has
the right domain context before planning tool calls.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("workbench.agents.harness.skills_loader")

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SKILLS_DIR = REPO_ROOT / "config" / "skills"


@dataclass
class SkillFile:
    slug: str
    path: Path
    body: str = ""
    loaded: str = ""              # "always" or empty
    loaded_when: str = ""         # keyword spec
    keywords: list[str] = field(default_factory=list)

    @property
    def is_always(self) -> bool:
        return self.loaded == "always"


_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)", re.S)


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    raw, body = m.group(1), m.group(2)
    fm: dict[str, str] = {}
    for line in raw.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip().strip('"')
    return fm, body


def _extract_keywords(loaded_when: str) -> list[str]:
    """`loaded_when: "any of: a, b, c"` → ['a', 'b', 'c']"""
    s = loaded_when.lower()
    if "any of:" in s:
        s = s.split("any of:", 1)[1]
    parts = [p.strip().strip("'\"`") for p in s.replace(";", ",").split(",")]
    return [p for p in parts if p]


class SkillsLoader:
    """Token-budget-aware assembler.

    Usage:
        loader = SkillsLoader()
        ctx = loader.build_context(user_text="Design a beta-lactam for MRSA")
        # ctx is a single string ready to drop into a system prompt
    """

    def __init__(
        self,
        skills_dir: Path = DEFAULT_SKILLS_DIR,
        max_context_tokens: int = 6000,
        cache_ttl_seconds: int = 60,
    ):
        self.skills_dir = skills_dir
        self.max_context_tokens = max_context_tokens
        self.cache_ttl = cache_ttl_seconds
        self._files_cache: list[SkillFile] | None = None
        self._files_loaded_at: float = 0.0

    # ---- file loading ----

    def _all_files(self) -> list[SkillFile]:
        now = time.time()
        if self._files_cache and (now - self._files_loaded_at) < self.cache_ttl:
            return self._files_cache
        files: list[SkillFile] = []
        if not self.skills_dir.exists():
            log.warning("skills dir %s does not exist", self.skills_dir)
            self._files_cache = []
            self._files_loaded_at = now
            return []
        for p in sorted(self.skills_dir.rglob("*.md")):
            try:
                text = p.read_text()
            except OSError:
                continue
            fm, body = _parse_frontmatter(text)
            slug = fm.get("slug") or str(p.relative_to(self.skills_dir).with_suffix(""))
            files.append(SkillFile(
                slug=slug,
                path=p,
                body=body.strip(),
                loaded=fm.get("loaded", ""),
                loaded_when=fm.get("loaded_when", ""),
                keywords=_extract_keywords(fm.get("loaded_when", "")),
            ))
        self._files_cache = files
        self._files_loaded_at = now
        return files

    # ---- matching ----

    def _matches(self, sf: SkillFile, user_text: str) -> bool:
        if sf.is_always:
            return True
        if not sf.keywords:
            return False
        lower = user_text.lower()
        return any(kw in lower for kw in sf.keywords)

    # ---- token-budget pack ----

    @staticmethod
    def _approx_tokens(text: str) -> int:
        """Approximate: 1 token ≈ 4 chars."""
        return max(1, len(text) // 4)

    def build_context(
        self,
        user_text: str,
        scenario_hint: Optional[str] = None,
        entity_hints: Optional[list[str]] = None,
    ) -> str:
        """Return a single context string. Always-loaded first, then
        domain matches, then scenario, then entities. Cuts at budget.
        """
        all_files = self._all_files()
        chosen: list[SkillFile] = []
        seen_slugs: set[str] = set()

        # 1. Always
        for sf in all_files:
            if sf.is_always and sf.slug not in seen_slugs:
                chosen.append(sf); seen_slugs.add(sf.slug)

        # 2. Domain matches
        for sf in all_files:
            if sf.slug in seen_slugs:
                continue
            if "/domains/" in str(sf.path) and self._matches(sf, user_text):
                chosen.append(sf); seen_slugs.add(sf.slug)

        # 3. Scenario
        for sf in all_files:
            if sf.slug in seen_slugs:
                continue
            if "/scenarios/" in str(sf.path):
                if scenario_hint and scenario_hint in sf.slug:
                    chosen.append(sf); seen_slugs.add(sf.slug)
                elif self._matches(sf, user_text):
                    chosen.append(sf); seen_slugs.add(sf.slug)

        # 4. Entity matches (drug names, pathogens, PDB IDs)
        if entity_hints:
            for sf in all_files:
                if sf.slug in seen_slugs:
                    continue
                if "/entities/" in str(sf.path):
                    if any(h.lower() in sf.slug.lower() for h in entity_hints):
                        chosen.append(sf); seen_slugs.add(sf.slug)

        # 5. Pack within token budget
        out_parts: list[str] = []
        used = 0
        for sf in chosen:
            chunk = f"<!-- {sf.slug} -->\n{sf.body}\n\n"
            t = self._approx_tokens(chunk)
            if used + t > self.max_context_tokens:
                log.info("skills budget hit at %s: %d tokens used, dropping rest",
                         sf.slug, used)
                break
            out_parts.append(chunk)
            used += t

        log.info("skills_loader: assembled %d files, ~%d tokens",
                 len(out_parts), used)
        return "".join(out_parts)

    # ---- introspection ----

    def manifest(self) -> list[dict[str, Any]]:
        """Inspect what's available. Used by /skills system command."""
        return [
            {
                "slug": sf.slug,
                "path": str(sf.path.relative_to(REPO_ROOT)),
                "loaded": "always" if sf.is_always else "conditional",
                "keywords": sf.keywords[:6],
            }
            for sf in self._all_files()
        ]
