"""newsline CLI."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from .config import Config
from .db import Database, default_data_dir
from .pipeline import Pipeline

console = Console()


@click.group()
@click.option("--config", "config_path", type=click.Path(path_type=Path), default="config.json",
              show_default=True, help="Path to config.json")
@click.pass_context
def cli(ctx: click.Context, config_path: Path) -> None:
    """newsline — a personal news radar that tracks storylines."""
    ctx.ensure_object(dict)
    ctx.obj["config"] = Config.load(config_path)
    ctx.obj["db"] = Database()


@cli.command()
@click.option("--hours", type=int, default=None, help="Override fetch window")
@click.option("--no-score", is_flag=True, help="Skip AI scoring step")
@click.option("--no-match", is_flag=True, help="Skip storyline matching step")
@click.option("--no-rewrite", is_flag=True, help="Skip stale-summary rewrite step")
@click.pass_context
def run(ctx: click.Context, hours: int | None, no_score: bool, no_match: bool,
        no_rewrite: bool) -> None:
    """Fetch → score → match → rewrite stale story summaries."""
    pipeline = Pipeline(ctx.obj["config"], ctx.obj["db"], console=console)

    async def _go() -> None:
        await pipeline.fetch_all(force_hours=hours)
        if not no_score:
            await pipeline.score_pending()
        if not no_match:
            await pipeline.match_storylines()
        if not no_rewrite:
            await pipeline.rewrite_stale_summaries()

    asyncio.run(_go())


@cli.command(name="list")
@click.option("--limit", type=int, default=20, show_default=True)
@click.option("--min-score", type=float, default=None,
              help="Defaults to filtering.ai_score_threshold from config")
@click.pass_context
def list_cmd(ctx: click.Context, limit: int, min_score: float | None) -> None:
    """List top scored items."""
    cfg = ctx.obj["config"]
    db = ctx.obj["db"]
    threshold = min_score if min_score is not None else cfg.filtering.ai_score_threshold

    items = db.top_items(limit=limit, min_score=threshold)
    if not items:
        console.print(f"No items with score ≥ {threshold}. Try `newsline run` first.")
        return

    table = Table(show_lines=False, expand=True)
    table.add_column("Score", justify="right", width=5)
    table.add_column("Source", width=14)
    table.add_column("Title")
    table.add_column("Tags", width=24)

    for it in items:
        table.add_row(
            f"{it.ai_score:.1f}" if it.ai_score is not None else "-",
            f"{it.source_type.value}/{(it.source_name or '')[:10]}",
            it.title,
            ", ".join(it.ai_tags[:3]),
        )
    console.print(table)


@cli.command()
@click.option("--limit", type=int, default=20, show_default=True)
@click.pass_context
def stories(ctx: click.Context, limit: int) -> None:
    """List active storylines, freshest first."""
    db = ctx.obj["db"]
    rows = db.active_stories(limit=limit)
    if not rows:
        console.print("No storylines yet. Try `newsline run` first.")
        return

    table = Table(show_lines=False, expand=True)
    table.add_column("ID", width=12)
    table.add_column("Events", justify="right", width=6)
    table.add_column("Top", justify="right", width=4)
    table.add_column("Updated", width=10)
    table.add_column("Title")

    for r in rows:
        lu = r["last_updated_at"]
        updated = lu.strftime("%Y-%m-%d") if hasattr(lu, "strftime") else str(lu or "")[:10]
        top = r.get("top_score")
        table.add_row(
            r["id"],
            str(r.get("event_count") or 0),
            f"{top:.1f}" if top is not None else "-",
            updated,
            r["title"],
        )
    console.print(table)


@cli.command()
@click.argument("story_id")
@click.pass_context
def story(ctx: click.Context, story_id: str) -> None:
    """Show one storyline and all its events (id or unique prefix)."""
    db = ctx.obj["db"]
    full_id = db.resolve_story_id(story_id) or story_id
    events = db.story_events(full_id)
    if not events:
        console.print(f"No events for story {story_id}.")
        return

    console.print(f"[bold]Story {full_id}[/bold] — {len(events)} event(s)")
    for it in events:
        ts = it.published_at.strftime("%Y-%m-%d %H:%M") if it.published_at else "  -  "
        console.print(
            f"  • {ts}  [dim]{it.source_type.value}[/dim]  "
            f"[cyan]{it.ai_score or 0:.1f}[/cyan]  {it.title}"
        )
        if it.ai_summary:
            console.print(f"      [dim]{it.ai_summary}[/dim]")


@cli.command()
@click.argument("story_id")
@click.argument("question")
@click.pass_context
def chat(ctx: click.Context, story_id: str, question: str) -> None:
    """Ask a question grounded in one storyline's events."""
    from .ai.chatter import Chatter
    from .ai.client import create_client

    db = ctx.obj["db"]
    cfg = ctx.obj["config"]

    full_id = db.resolve_story_id(story_id) or story_id
    events = db.story_events(full_id)
    if not events:
        console.print(f"No events for story {story_id!r}.")
        raise SystemExit(1)

    # Look up story metadata for title/summary
    with db.conn() as c:
        row = c.execute(
            "SELECT title, summary FROM stories WHERE id = ?", (full_id,)
        ).fetchone()
    title = row["title"] if row else full_id
    summary = row["summary"] if row else None

    async def _go() -> None:
        client = create_client(cfg.ai)
        chatter = Chatter(client, language=cfg.ai.language)
        answer = await chatter.ask(
            title=title, summary=summary, events=events, question=question
        )
        console.print(answer)

    asyncio.run(_go())


@cli.command()
@click.option("--days", type=int, default=1, show_default=True,
              help="Window: stories updated in the last N days")
@click.option("--top", type=int, default=20, show_default=True)
@click.option("--min-score", type=float, default=None,
              help="Defaults to filtering.ai_score_threshold from config")
@click.option("-o", "--output", type=click.Path(path_type=Path), default=None,
              help="Write to file instead of stdout (also prints path)")
@click.pass_context
def digest(ctx: click.Context, days: int, top: int, min_score: float | None,
           output: Path | None) -> None:
    """Render a markdown digest of recent storylines."""
    from . import digest as digest_mod
    cfg = ctx.obj["config"]
    db = ctx.obj["db"]
    threshold = min_score if min_score is not None else cfg.filtering.ai_score_threshold
    text = digest_mod.render(db, days=days, top=top, min_score=threshold)
    if output:
        written = digest_mod.write(text, output)
        console.print(f"Wrote {written}")
    else:
        # Use plain print so pipes / redirection don't get Rich's box-drawing.
        click.echo(text)


@cli.command()
@click.option("--days", type=int, default=30, show_default=True)
@click.pass_context
def signals(ctx: click.Context, days: int) -> None:
    """Summarize user feedback signals (open/dwell/thumbs)."""
    summary = ctx.obj["db"].signal_summary(days=days)

    if not summary["by_kind"]:
        console.print(f"No signals in the last {days} days.")
        return

    console.print(f"[bold]Signals over the last {days} days[/bold]")
    for kind, n in summary["by_kind"].items():
        console.print(f"  {kind:<12} {n}")
    if summary["avg_dwell_ms"]:
        avg = summary["avg_dwell_ms"] / 1000.0
        console.print(f"  avg dwell    {avg:.1f}s  (n={summary['dwell_count']})")

    if summary["recent"]:
        console.print("\n[bold]Recent[/bold]")
        for r in summary["recent"]:
            val = ""
            if r["kind"] == "dwell_ms" and r["value"]:
                val = f"  {r['value']/1000:.1f}s"
            console.print(
                f"  {str(r['ts'])[:19]}  {r['kind']:<12}{val}  {r['title'][:60]}"
            )


@cli.command(name="retranslate")
@click.option("--summaries/--no-summaries", default=True, show_default=True)
@click.option("--titles/--no-titles", default=True, show_default=True)
@click.pass_context
def retranslate(ctx: click.Context, summaries: bool, titles: bool) -> None:
    """Re-translate story summaries and/or titles to match ai.language.

    Use this after switching language; existing rows were generated in
    the old language and won't change on their own.
    """
    from datetime import datetime, timezone

    from .ai.client import create_client
    from .ai.rewriter import SummaryRewriter
    from .ai.translator import TitleTranslator

    cfg = ctx.obj["config"]
    db = ctx.obj["db"]
    client = create_client(cfg.ai)

    if summaries:
        targets = db.stories_in_wrong_language(cfg.ai.language)
        if targets:
            console.print(f"📝 Summaries: rewriting {len(targets)} stories in {cfg.ai.language!r}")
            rewriter = SummaryRewriter(client, language=cfg.ai.language)

            async def _one_summary(row: dict) -> bool:
                events = db.story_events(row["id"])
                if not events:
                    return False
                new_summary = await rewriter.rewrite(row["title"], events)
                if not new_summary:
                    return False
                db.update_story_summary(row["id"], new_summary, datetime.now(timezone.utc))
                return True

            async def _go() -> int:
                results = await asyncio.gather(
                    *(_one_summary(t) for t in targets), return_exceptions=True
                )
                return sum(1 for r in results if r is True)

            done = asyncio.run(_go())
            console.print(f"  ✓ {done}/{len(targets)} summaries")
        else:
            console.print(f"📝 Summaries: all in {cfg.ai.language!r} already")

    if titles:
        if cfg.ai.language.lower() != "zh":
            console.print("🏷  Titles: skipping — only zh target supported right now")
        else:
            targets = db.stories_with_wrong_language_title(cfg.ai.language)
            if not targets:
                console.print(f"🏷  Titles: all in {cfg.ai.language!r} already")
            else:
                console.print(f"🏷  Titles: translating {len(targets)} story titles")
                translator = TitleTranslator(client, language=cfg.ai.language)

                async def _one_title(row: dict) -> bool:
                    new_title = await translator.translate(row["title"])
                    if not new_title or new_title == row["title"]:
                        return False
                    db.update_story_title(row["id"], new_title)
                    return True

                async def _go() -> int:
                    results = await asyncio.gather(
                        *(_one_title(t) for t in targets), return_exceptions=True
                    )
                    return sum(1 for r in results if r is True)

                done = asyncio.run(_go())
                console.print(f"  ✓ {done}/{len(targets)} titles")


@cli.command()
@click.option("--port", type=int, default=8137, show_default=True,
              help="Localhost port to bind")
@click.pass_context
def serve(ctx: click.Context, port: int) -> None:
    """Run the chat sidecar HTTP server on 127.0.0.1."""
    from . import server
    asyncio.run(server.run(ctx.obj["config"], ctx.obj["db"], port=port))


@cli.command()
def where() -> None:
    """Print the local data directory."""
    d = default_data_dir()
    console.print(str(d))
    console.print(f"db: {d / 'newsline.db'}")


def main() -> None:
    cli(obj={})


if __name__ == "__main__":
    main()
