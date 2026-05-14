"""Render an active-storylines digest as Markdown.

Pulled out into its own module so the CLI command and any future
exporters (email, webhook) share the same rendering.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from .db import Database


def render(db: Database, *, days: int = 1, top: int = 20,
           min_score: float = 4.0) -> str:
    """Build the digest text. Pure function; takes the db and returns markdown."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    with db.conn() as c:
        rows = c.execute(
            """
            SELECT s.id, s.title, s.summary, s.last_updated_at,
                   COUNT(ci.id) AS event_count,
                   MAX(ci.ai_score) AS top_score
              FROM stories s
              JOIN content_items ci ON ci.story_id = s.id
             WHERE s.status = 'active'
               AND s.last_updated_at >= ?
               AND ci.ai_score >= ?
          GROUP BY s.id
          ORDER BY top_score DESC, s.last_updated_at DESC
             LIMIT ?
            """,
            (cutoff, min_score, top),
        ).fetchall()

        stories = [dict(r) for r in rows]
        for s in stories:
            ev = c.execute(
                """
                SELECT title, url, ai_score, source_type, source_name, published_at
                  FROM content_items
                 WHERE story_id = ?
                 ORDER BY ai_score DESC, published_at DESC
                """,
                (s["id"],),
            ).fetchall()
            s["events"] = [dict(e) for e in ev]

    lines: list[str] = []
    lines.append(f"# Newsline — {today}")
    if not stories:
        lines.append("")
        lines.append(f"_No stories in the last {days}d with score ≥ {min_score}._")
        return "\n".join(lines)

    lines.append("")
    lines.append(f"_{len(stories)} stories from the last {days}d, score ≥ {min_score}._")
    lines.append("")

    for i, s in enumerate(stories, 1):
        score = s["top_score"]
        score_str = f"⭐ {score:.1f}" if score is not None else ""
        marker = f"{s['event_count']}×" if s["event_count"] > 1 else ""
        lines.append(f"## {i}. {s['title']}  {score_str} {marker}".rstrip())
        if s.get("summary"):
            lines.append("")
            lines.append(s["summary"])
        lines.append("")
        # Compact event list: one bullet per source
        for e in s["events"]:
            src = f"{e['source_type']}/{e['source_name'] or ''}"
            es = f"{e['ai_score']:.1f}" if e.get("ai_score") is not None else "-"
            title = e["title"].replace("|", "\\|")
            lines.append(f"- `{es}` [{title}]({e['url']}) — _{src}_")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write(text: str, path: Path | None) -> Path | None:
    if path is None:
        return None
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
