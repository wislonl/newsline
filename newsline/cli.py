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
@click.pass_context
def run(ctx: click.Context, hours: int | None, no_score: bool) -> None:
    """Fetch new items from all sources and score them."""
    pipeline = Pipeline(ctx.obj["config"], ctx.obj["db"], console=console)

    async def _go() -> None:
        await pipeline.fetch_all(force_hours=hours)
        if not no_score:
            await pipeline.score_pending()

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
def where() -> None:
    """Print the local data directory."""
    d = default_data_dir()
    console.print(str(d))
    console.print(f"db: {d / 'newsline.db'}")


def main() -> None:
    cli(obj={})


if __name__ == "__main__":
    main()
