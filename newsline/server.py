"""Localhost-only HTTP sidecar.

Started by the Mac app on launch (`newsline serve --port <p>`). Exposes
one streaming chat endpoint so the UI can render tokens as they arrive
instead of waiting 3–5s on each subprocess spawn.

The server binds 127.0.0.1 only — never reachable from the network.
"""

from __future__ import annotations

import asyncio
import json
import logging

from aiohttp import web

from .ai.chatter import Chatter
from .ai.client import create_client
from .config import Config
from .db import Database

log = logging.getLogger("newsline.server")


def make_app(config: Config, db: Database) -> web.Application:
    app = web.Application()
    app["config"] = config
    app["db"] = db
    app["llm"] = create_client(config.ai)
    app.router.add_get("/healthz", _healthz)
    app.router.add_post("/chat", _chat)
    return app


async def _healthz(_req: web.Request) -> web.Response:
    return web.json_response({"ok": True})


async def _chat(req: web.Request) -> web.StreamResponse:
    """POST /chat
    body: {"story_id": "<id or prefix>", "question": "..."}
    returns: text/plain stream, NDJSON-encoded
             {"chunk": "..."}     repeatedly
             {"done": true}       once at the end
             {"error": "..."}     on failure
    """
    try:
        payload = await req.json()
    except Exception:
        return web.json_response({"error": "invalid JSON"}, status=400)

    story_id = (payload.get("story_id") or "").strip()
    question = (payload.get("question") or "").strip()
    if not story_id or not question:
        return web.json_response({"error": "story_id and question required"}, status=400)

    raw_history = payload.get("history") or []
    history: list[dict[str, str]] = []
    if isinstance(raw_history, list):
        for turn in raw_history:
            if (isinstance(turn, dict)
                    and turn.get("role") in ("user", "assistant")
                    and isinstance(turn.get("content"), str)):
                history.append({"role": turn["role"], "content": turn["content"]})

    db: Database = req.app["db"]
    full_id = db.resolve_story_id(story_id) or story_id
    events = db.story_events(full_id)
    if not events:
        return web.json_response({"error": f"no events for story {story_id!r}"}, status=404)

    with db.conn() as c:
        row = c.execute(
            "SELECT title, summary FROM stories WHERE id = ?", (full_id,)
        ).fetchone()
    title = row["title"] if row else full_id
    summary = row["summary"] if row else None

    config: Config = req.app["config"]
    chatter = Chatter(req.app["llm"], language=config.ai.language)

    resp = web.StreamResponse(
        status=200,
        headers={
            "Content-Type": "application/x-ndjson",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
    await resp.prepare(req)

    try:
        async for chunk in chatter.ask_stream(
            title=title, summary=summary, events=events,
            question=question, history=history,
        ):
            await resp.write(json.dumps({"chunk": chunk}).encode("utf-8") + b"\n")
        await resp.write(json.dumps({"done": True}).encode("utf-8") + b"\n")
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.warning("chat stream failed: %s", e)
        await resp.write(json.dumps({"error": str(e)}).encode("utf-8") + b"\n")
    finally:
        await resp.write_eof()
    return resp


async def run(config: Config, db: Database, *, port: int = 8137) -> None:
    """Block forever serving on 127.0.0.1:<port>."""
    app = make_app(config, db)
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, host="127.0.0.1", port=port)
    await site.start()
    log.info("newsline server listening on http://127.0.0.1:%d", port)
    print(f"newsline serve: http://127.0.0.1:{port}", flush=True)
    try:
        # Sleep forever; serve until interrupted.
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()
