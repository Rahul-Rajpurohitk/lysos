"""verify_keys.py — pre-flight credential check for Lysos training.

Run BEFORE provisioning the AMD MI300X VM, BEFORE launching any stage.
A missing key during a 4-day training run is a budget-burning disaster.

Exit codes:
  0 = all REQUIRED keys present and live
  1 = at least one REQUIRED key missing or unreachable
  2 = recommended keys missing (still launches but with degraded features)

Required:
  HF_TOKEN          — write scope (push models + datasets)
  GEMINI_API_KEY    — embedding_novelty real signal (Gemini Embedding 2)

Recommended:
  WANDB_API_KEY     — live training dashboard
  HF_PRO_FLAG       — verified via /api/whoami-v2 (read response)

Optional:
  OPENAI_API_KEY    — comparator benchmark only
  ANTHROPIC_API_KEY — comparator benchmark only
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path


def _load_dotenv(path: Path = Path(".env")) -> None:
    """Minimal .env loader; respects existing env vars."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip()
        if k and k not in os.environ:
            os.environ[k] = v


def _http(url: str, headers: dict, body: bytes | None = None,
          method: str = "GET", timeout: float = 15.0) -> tuple[int, str]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        return -1, f"{type(e).__name__}: {e}"


# ----------------------------------------------------------------------
# Per-service checks (live API calls; small payload to stay free)
# ----------------------------------------------------------------------

def check_gemini(key: str) -> tuple[bool, str]:
    code, body = _http(
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-embedding-001:embedContent",
        headers={"Content-Type": "application/json", "X-goog-api-key": key},
        body=json.dumps({
            "content": {"parts": [{"text": "CCO"}]},
            "taskType": "RETRIEVAL_DOCUMENT",
        }).encode("utf-8"),
        method="POST",
    )
    if code != 200:
        return False, f"HTTP {code}: {body[:200]}"
    try:
        dim = len(json.loads(body)["embedding"]["values"])
        return True, f"OK dim={dim}"
    except Exception as e:  # noqa: BLE001
        return False, f"parse error: {e}"


def check_hf(token: str) -> tuple[bool, str]:
    code, body = _http(
        "https://huggingface.co/api/whoami-v2",
        headers={"Authorization": f"Bearer {token}"},
    )
    if code != 200:
        return False, f"HTTP {code}: {body[:200]}"
    try:
        d = json.loads(body)
    except Exception as e:  # noqa: BLE001
        return False, f"parse: {e}"
    name = d.get("name") or d.get("fullname") or "?"
    auth = d.get("auth", {})
    access = auth.get("accessToken", {}) or {}
    role = access.get("role", "?")
    is_pro = "pro" in str(d.get("type", "")).lower() or d.get("isPro") is True
    if role != "write":
        return False, f"token role={role} (need write); user={name}"
    suffix = " [Pro]" if is_pro else ""
    return True, f"OK user={name} role=write{suffix}"


def check_wandb(key: str) -> tuple[bool, str]:
    """wandb verifies via REST viewer query.

    Accepts both formats:
      - legacy 40-char hex
      - v1 long-form (`wandb_v1_…`)
    """
    if not (len(key) == 40 or key.startswith("wandb_v1_")):
        return False, f"unrecognized key format (len={len(key)})"
    code, body = _http(
        "https://api.wandb.ai/graphql",
        headers={
            "Authorization": f"Basic {_b64(b'api:' + key.encode())}",
            "Content-Type": "application/json",
        },
        body=json.dumps({"query": "{viewer{username entity}}"}).encode("utf-8"),
        method="POST",
    )
    if code != 200:
        return False, f"HTTP {code}: {body[:200]}"
    try:
        v = json.loads(body)["data"]["viewer"]
        u = v.get("username") or "?"
        e = v.get("entity") or u
        return True, f"OK user={u} entity={e}"
    except Exception as e:  # noqa: BLE001
        return False, f"parse: {e}"


def _b64(b: bytes) -> str:
    import base64
    return base64.b64encode(b).decode("ascii")


def check_openai(key: str) -> tuple[bool, str]:
    code, body = _http(
        "https://api.openai.com/v1/models",
        headers={"Authorization": f"Bearer {key}"},
    )
    if code != 200:
        return False, f"HTTP {code}: {body[:200]}"
    return True, "OK"


def check_anthropic(key: str) -> tuple[bool, str]:
    code, body = _http(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        body=json.dumps({
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 4,
            "messages": [{"role": "user", "content": "ok"}],
        }).encode("utf-8"),
        method="POST",
    )
    if code in (200, 400):  # 400 may still mean key valid; auth is 401
        return True, f"OK (HTTP {code})"
    return False, f"HTTP {code}: {body[:200]}"


# ----------------------------------------------------------------------
# Driver
# ----------------------------------------------------------------------

REQUIRED = [
    ("HF_TOKEN", check_hf),
    ("GEMINI_API_KEY", check_gemini),
]
RECOMMENDED = [
    ("WANDB_API_KEY", check_wandb),
]
OPTIONAL = [
    ("OPENAI_API_KEY", check_openai),
    ("ANTHROPIC_API_KEY", check_anthropic),
]


def _load_hf_cache_token() -> None:
    """If HF_TOKEN not set, fall back to the standard huggingface-cli cache.

    This is the canonical token location used by huggingface_hub itself, so
    it's safe and avoids duplicating credentials into .env.
    """
    if os.environ.get("HF_TOKEN"):
        return
    for p in (Path.home() / ".cache" / "huggingface" / "token",
              Path.home() / ".huggingface" / "token"):
        if p.exists():
            try:
                tok = p.read_text().strip()
                if tok:
                    os.environ["HF_TOKEN"] = tok
                    return
            except OSError:
                pass


def _load_wandb_netrc() -> None:
    """Fallback: read WANDB key from ~/.netrc (where `wandb login` puts it)."""
    if os.environ.get("WANDB_API_KEY"):
        return
    netrc = Path.home() / ".netrc"
    if not netrc.exists():
        return
    try:
        text = netrc.read_text()
    except OSError:
        return
    # Simple parser: look for "machine api.wandb.ai" then "password <KEY>"
    in_block = False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("machine "):
            in_block = "api.wandb.ai" in s
        elif in_block and s.startswith("password "):
            tok = s.split(None, 1)[1].strip()
            if tok:
                os.environ["WANDB_API_KEY"] = tok
                return


def run() -> int:
    _load_dotenv(Path(__file__).parent.parent / ".env")
    _load_hf_cache_token()
    _load_wandb_netrc()
    rows: list[tuple[str, str, str, str]] = []  # (tier, key, status, detail)

    fail_required = False
    fail_recommended = False

    for tier, items, fail_fn in [
        ("REQUIRED", REQUIRED, "fail_required"),
        ("RECOMMENDED", RECOMMENDED, "fail_recommended"),
        ("OPTIONAL", OPTIONAL, None),
    ]:
        for var, fn in items:
            val = os.environ.get(var, "").strip()
            if not val:
                rows.append((tier, var, "MISSING", "not set in env or .env"))
                if tier == "REQUIRED":
                    fail_required = True
                elif tier == "RECOMMENDED":
                    fail_recommended = True
                continue
            ok, detail = fn(val)
            rows.append((tier, var, "OK" if ok else "FAIL", detail))
            if not ok:
                if tier == "REQUIRED":
                    fail_required = True
                elif tier == "RECOMMENDED":
                    fail_recommended = True

    print("=" * 78)
    print(f"{'TIER':<14}{'KEY':<22}{'STATUS':<10}DETAIL")
    print("-" * 78)
    for tier, key, status, detail in rows:
        print(f"{tier:<14}{key:<22}{status:<10}{detail}")
    print("=" * 78)

    if fail_required:
        print("\n[X] REQUIRED key(s) missing/invalid. Training will not start.")
        print("    Fix .env or `export VAR=...` and rerun.")
        return 1
    if fail_recommended:
        print("\n[!] All required keys OK but recommended key(s) missing.")
        print("    Training will run with degraded monitoring/features.")
        return 2
    print("\n[OK] All keys present and live. Cleared for training.")
    return 0


if __name__ == "__main__":
    sys.exit(run())
