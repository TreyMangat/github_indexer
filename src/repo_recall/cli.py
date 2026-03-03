from __future__ import annotations

import json

import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from .config import get_settings
from .db import connect, init_db
from .indexer.indexer import RepoIndexer
from .logging import setup_logging
from .retrieval.search import search_repos

app = typer.Typer(add_completion=False, help="Repo Recall — git repo indexer + recall API")
console = Console()


@app.callback()
def _main(log_level: str = typer.Option("INFO", help="Log level (DEBUG/INFO/WARN/ERROR)")) -> None:
    setup_logging(level=log_level)


@app.command("init-db")
def init_db_cmd() -> None:
    """Initialize Postgres schema (idempotent)."""
    settings = get_settings()
    with connect(settings) as conn:
        init_db(conn)
    console.print("[green]DB initialized[/green]")


@app.command()
def index(
    repo: str = typer.Option(..., "--repo", help="Local path or git URL"),
    no_incremental: bool = typer.Option(False, "--no-incremental", help="Reindex everything"),
) -> None:
    """Index a repository."""
    settings = get_settings()
    idx = RepoIndexer(settings)
    stats = idx.index(repo, incremental=not no_incremental)
    console.print(
        f"[green]Indexed[/green] repo_id={stats.repo_id} files_seen={stats.files_seen} files_indexed={stats.files_indexed} chunks_indexed={stats.chunks_indexed}"
    )


@app.command()
def update(
    repo: str = typer.Option(..., "--repo", help="Local path or git URL"),
) -> None:
    """Incrementally update an existing repo index (alias of index)."""
    settings = get_settings()
    idx = RepoIndexer(settings)
    stats = idx.index(repo, incremental=True)
    console.print(
        f"[green]Updated[/green] repo_id={stats.repo_id} files_seen={stats.files_seen} files_indexed={stats.files_indexed} chunks_indexed={stats.chunks_indexed}"
    )


@app.command()
def search(
    query: str = typer.Argument(..., help="Natural language query / prompt"),
    top_k_repos: int = typer.Option(5, "--top-k-repos", min=1, max=20),
    top_k_chunks: int = typer.Option(3, "--top-k-chunks", min=1, max=10),
    json_out: bool = typer.Option(False, "--json", help="Print raw JSON instead of a table"),
) -> None:
    """Search for the best candidate repos for a prompt."""
    settings = get_settings()
    with connect(settings) as conn:
        result = search_repos(
            conn,
            settings=settings,
            query=query,
            top_k_repos=top_k_repos,
            top_k_chunks=top_k_chunks,
        )

    if json_out:
        console.print_json(json.dumps(result))
        return

    table = Table(title=f"Repo Recall — results for: {query}")
    table.add_column("#", justify="right", style="bold")
    table.add_column("Repo")
    table.add_column("Source")
    table.add_column("Score", justify="right")
    table.add_column("Evidence (top chunk)")

    for i, r in enumerate(result["results"], start=1):
        repo = r["repo"]
        ev0 = r["evidence"][0] if r["evidence"] else {}
        ev_text = (ev0.get("text") or "").replace("\n", " ")
        ev_text = ev_text[:140] + ("…" if len(ev_text) > 140 else "")
        table.add_row(
            str(i),
            str(repo.get("name") or ""),
            f"{repo.get('source')}:{repo.get('source_ref')}",
            f"{r.get('score'):.3f}",
            f"{ev0.get('file_path')}:{ev0.get('start_line')}-{ev0.get('end_line')} {ev_text}",
        )

    console.print(table)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8080, "--port"),
) -> None:
    """Run the FastAPI server."""
    uvicorn.run("repo_recall.api.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    app()
