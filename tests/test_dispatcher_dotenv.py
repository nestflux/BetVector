"""The WC dispatcher must load .env via python-dotenv before any DB access.

It is launched by a shell runner that does `set -a; source .env`, but the Neon
DATABASE_URL ends in an unquoted '&' (...&channel_binding=require), which bash
treats as a background operator → DATABASE_URL ends up UNSET → db.py falls back
to local SQLite (a split-brain that stranded captured lineups in the backup
instead of Neon). python-dotenv parses '&' correctly, so main() must call it
before run_dispatcher() — the same pattern src/world_cup/pipeline.py uses.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "src" / "world_cup" / "dispatcher.py").read_text()


def test_dispatcher_main_loads_dotenv_before_running():
    assert "load_dotenv" in SRC, "dispatcher must call load_dotenv"
    main = next(
        (n for n in ast.walk(ast.parse(SRC))
         if isinstance(n, ast.FunctionDef) and n.name == "main"),
        None,
    )
    assert main is not None, "dispatcher.main() not found"
    body = ast.unparse(main)
    assert "load_dotenv" in body, "load_dotenv must be called inside main()"
    assert body.index("load_dotenv") < body.index("run_dispatcher"), \
        "load_dotenv must run before run_dispatcher() (env set before any DB access)"


def test_wc_pipeline_also_loads_dotenv():
    """Guard the sibling pattern so the pipeline never regresses to shell-only."""
    pipe = (ROOT / "src" / "world_cup" / "pipeline.py").read_text()
    assert "load_dotenv" in pipe
