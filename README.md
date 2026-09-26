# sqlmodel-export

Export SQLAlchemy or SQLModel metadata as creation SQL for PostgreSQL, SQLite,
or MySQL. Requires Python 3.10+ and SQLAlchemy 2.0; generation works offline
without database credentials, database drivers, or Alembic.

## Install and run

Install this checkout in your application's Python environment:

```sh
uv pip install /path/to/sqlmodel-export
uv pip install -e /path/to/your/application
```

Activate that environment before running the console command. For a uv-managed
application, you can instead add the local package with
`uv add /path/to/sqlmodel-export` and invoke the command with `uv run`.
Applications using SQLModel supply their own SQLModel installation.

```sh
sqlmodel-export myapp.models:Base.metadata --dialect postgresql --output schema.sql
sqlmodel-export myapp.models:SQLModel.metadata --dialect sqlite
sqlmodel-export myapp.models:metadata --dialect mysql
```

Omit `--output` to print SQL to stdout. `--help` shows the available arguments.
Targets use `module.path:attribute.path`, with Python identifiers in each dotted
segment. The resolved value must be a nonempty `sqlalchemy.MetaData` instance.

## Register every model

Make the target module import every model whose table should be exported.
For example, `myapp/models/__init__.py` for a SQLModel application can contain:

```python
from sqlmodel import SQLModel
from .user import User
from .order import Order
```

SQLAlchemy applications can expose their declarative `Base` in the same way.
Table registration happens when model definitions execute. Importing only
`SQLModel` produces empty metadata; importing only some models can produce an
incomplete schema that the exporter cannot detect. Install applications with a
`src/` layout, or explicitly configure their Python import path. Resolution uses
the interpreter's ordinary import path and the attributes named in the target.

## Python API

```python
from sqlmodel_export import export_ddl, load_metadata

metadata = load_metadata("myapp.models:Base.metadata")
sql = export_ddl(metadata, dialect="postgresql")
```

Both functions validate the metadata. `export_ddl` returns the entire SQL string;
the caller chooses where to write it. Library calls preserve the caller's streams.

## Export behavior

The output follows SQLAlchemy's metadata creation sequence, including applicable
tables, constraints, indexes, PostgreSQL enums, and creation hooks. Cyclic foreign
keys can produce separate `ALTER TABLE` statements on PostgreSQL and MySQL.
SQLite follows its own constraint and ALTER behavior. Each emitted fragment ends
with a semicolon, fragments are separated by a blank line, and output ends with
a newline. Ordering follows SQLAlchemy and may vary across versions or processes.

Use metadata valid for the chosen dialect and database server version.
Vendor-specific types retain their dialect requirements. Schemas, extensions,
externally managed enums (`create_type=False`), and other external objects must
already exist unless your creation hooks emit them. This is an initial creation
export; schema comparison, migrations, DROP scripts, and data export are outside
its scope.

Import only trusted application code whose initialization works offline. Imports
and DDL hooks execute Python code, and that code can open its own connections.
Hooks must support SQLAlchemy's mock-engine DDL contract, without result-bearing
database queries. Custom DDL must emit complete SQL fragments, placing any final
semicolon after the last comment. The CLI sends ordinary Python stdout writes
during import and generation to stderr. Application code manages its own direct
file-descriptor and subprocess output.

Generation completes in memory before the destination is written. For file
output, the parent directory must exist. The CLI writes a temporary UTF-8 file
with LF newlines in that directory, closes it, and replaces the destination.
Existing files are replaced automatically; existing permissions and ownership
are not guaranteed to be preserved. A destination symlink is replaced while its
referent stays intact. Relative paths use the working directory; `-` names a
literal file. Generation failure preserves existing files and emits no SQL to
stdout. A stdout write failure can leave partial output.

Successful exports exit 0, usage errors exit 2, and ordinary import, compilation,
or output failures exit 1 with their original traceback. Application exits and
interrupts retain Python behavior.

## Development

```sh
uv sync --locked
uv run --locked pytest
uv run --locked --group compatibility pytest tests/compatibility
uv build
```

The default suite runs core tests. `uv sync --locked` creates a core environment
without SQLModel; the separate `compatibility` dependency group adds SQLModel.
Run all suites with `uv run --locked --group compatibility pytest tests`.

Installed-wheel tests use an isolated environment containing the wheel and its
runtime dependencies only:

```sh
uv venv .venv-wheel
uv pip install --python .venv-wheel/bin/python dist/sqlmodel_export-0.1.0-py3-none-any.whl
SQLMODEL_EXPORT_WHEEL_PYTHON="$PWD/.venv-wheel/bin/python" uv run --locked --group compatibility pytest tests
```

Use the corresponding `Scripts/python.exe` path on Windows. Without
`SQLMODEL_EXPORT_WHEEL_PYTHON`, the installation suite reports skips. Compatibility
validation covers Python 3.10–3.14, with SQLAlchemy 2.0.0 on Python 3.10 and the
latest allowed 2.0 release on the other versions. Build artifacts are written to
`dist/`; building does not publish them.
