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
        chatter = Chatter(client)
        answer = await chatter.ask(
            title=title, summary=summary, events=events, question=question
        )
        console.print(answer)

    asyncio.run(_go())


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
