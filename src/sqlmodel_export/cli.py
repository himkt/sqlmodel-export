import argparse
from contextlib import redirect_stdout
import os
from pathlib import Path
import sys
import tempfile

from .ddl import DIALECT_URLS, export_ddl
from .metadata import load_metadata, parse_target


def write_sql_file(destination: Path, sql: str) -> None:
    stream = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", dir=destination.parent,
        prefix=f".{destination.name}.", suffix=".tmp", delete=False,
    )
    temporary_path = Path(stream.name)
    try:
        with stream:
            stream.write(sql)
        os.replace(temporary_path, destination)
    finally:
        temporary_path.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export model metadata as offline creation DDL",
        epilog="Example: sqlmodel-export myapp.models:SQLModel.metadata "
        "--dialect postgresql --output schema.sql",
    )
    parser.add_argument("target", metavar="TARGET")
    parser.add_argument("--dialect", required=True, choices=tuple(DIALECT_URLS))
    parser.add_argument("--output", metavar="PATH", type=Path)
    arguments = parser.parse_args()
    try:
        parse_target(arguments.target)
    except ValueError as error:
        parser.error(str(error))
    with redirect_stdout(sys.stderr):
        metadata = load_metadata(arguments.target)
        sql = export_ddl(metadata, dialect=arguments.dialect)
    if arguments.output is None:
        sys.stdout.write(sql)
        sys.stdout.flush()
    else:
        write_sql_file(arguments.output, sql)
    return 0
