"""Diagnostics: validate config + API key + LLM round-trip + DB.

Run via `news doctor`. Each check prints a line with a status icon so the
user can see at a glance which piece is wrong.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .db import Database


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""


def _ok(name: str, detail: str = "") -> Check:
    return Check(name, True, detail)


def _fail(name: str, detail: str = "") -> Check:
    return Check(name, False, detail)


async def run_checks(config_path: Path | None = None) -> list[Check]:
    out: list[Check] = []

    # 1. config.json
    cfg_path = config_path or Path("config.json")
    if not cfg_path.exists():
        out.append(_fail("config.json", f"missing at {cfg_path}"))
        return out
    try:
        cfg = Config.load(cfg_path)
    except Exception as e:
        out.append(_fail("config.json", f"invalid: {e}"))
        return out
    out.append(_ok("config.json", f"provider={cfg.ai.provider}, model={cfg.ai.model}"))

    # 2. API key
    key = os.environ.get(cfg.ai.api_key_env, "")
    if not key:
        out.append(_fail(f"${cfg.ai.api_key_env}", "not set in environment"))
        return out
    out.append(_ok(f"${cfg.ai.api_key_env}", f"set ({len(key)} chars)"))

    # 3. LLM round-trip — one cheap request
    try:
        from .ai.client import create_client
        client = create_client(cfg.ai)
        t0 = time.perf_counter()
        reply = await client.complete_text(
            "You are a connectivity check.", "Reply with the single word: ok",
            max_tokens=8,
        )
        ms = (time.perf_counter() - t0) * 1000
        snippet = (reply or "").strip().splitlines()[-1][:40] if reply else ""
        out.append(_ok("LLM round-trip", f"{ms:.0f}ms · reply={snippet!r}"))
    except Exception as e:
        out.append(_fail("LLM round-trip", str(e)[:200]))
        return out

    # 4. SQLite DB
    try:
        db = Database()
        with db.conn() as c:
            n_stories = c.execute("SELECT COUNT(*) FROM stories").fetchone()[0]
            n_items = c.execute("SELECT COUNT(*) FROM content_items").fetchone()[0]
            wal = c.execute("PRAGMA journal_mode").fetchone()[0]
        out.append(_ok("SQLite", f"{db.path.name} · {n_stories} stories · {n_items} items · {wal}"))
    except Exception as e:
        out.append(_fail("SQLite", str(e)[:200]))

    # 5. uv executable in PATH (used by the Mac app's sidecar/pipeline spawns)
    import shutil
    uv = shutil.which("uv") or None
    if uv:
        out.append(_ok("uv binary", uv))
    else:
        out.append(_fail("uv binary", "not on PATH — Mac app subprocesses will fail unless $NEWSLINE_UV is set"))

    return out


def render(checks: list[Check]) -> str:
    lines: list[str] = []
    for ch in checks:
        icon = "✓" if ch.ok else "✗"
        line = f"  {icon} {ch.name}"
        if ch.detail:
            line += f"  —  {ch.detail}"
        lines.append(line)
    overall = "all checks passed" if all(c.ok for c in checks) else "some checks failed"
    lines.append(f"\n{overall}")
    return "\n".join(lines)


def main(config_path: Path | None = None) -> int:
    checks = asyncio.run(run_checks(config_path))
    print(render(checks))
    return 0 if all(c.ok for c in checks) else 1
