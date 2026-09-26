# sqlmodel-export: Offline DDL Export

**Status**: Complete
**Progress**: 6/6 tasks complete
**Last Updated**: 2026-09-26

## Overview

Build `sqlmodel-export`, an independent Python library and CLI that imports an application's model module, resolves a SQLAlchemy `MetaData` attribute, and exports its creation DDL to stdout or a SQL file. Support SQLAlchemy and SQLModel metadata without requiring a live database or Alembic migration scripts. This repository stores the design document; implementation belongs in a standalone package.

## Success Criteria

- [x] `sqlmodel-export myapp.models:SQLModel.metadata --dialect postgresql --output schema.sql` exports the imported models, and omitting `--output` prints the same SQL to stdout.
- [x] PostgreSQL, SQLite, and MySQL fixtures produce dialect-specific creation DDL, including applicable indexes, constraints, and PostgreSQL enum types.
- [x] Plain SQLAlchemy and SQLModel fixtures work through the same metadata contract on Python 3.14.
- [x] Export runs without database credentials, database services, Alembic, or PostgreSQL/MySQL DBAPI drivers.
- [x] Invalid targets, empty metadata, import failures, and compilation failures produce a nonzero exit; generation failure leaves an existing output file intact and emits no generated SQL to stdout.

---

## Specification

### Package and scope

Use distribution and executable name `sqlmodel-export`, import package `sqlmodel_export`, and a standard `src/` package layout. Declare Python `>=3.10` and runtime dependency `SQLAlchemy>=2.0,<2.1`. Use standard-library `argparse`, `importlib`, and file APIs; SQLModel belongs only in the compatibility-test dependencies. Applications using SQLModel supply their own SQLModel installation in the same Python environment.

Use `uv` for project dependency management, isolated environments, test execution, and package builds. Place the import package at `src/sqlmodel_export/`, record development dependencies in `pyproject.toml`, and maintain `uv.lock`. Document the corresponding `uv` commands for contributors.

The export represents the creation sequence of the supplied in-memory metadata. It covers all registered tables and the DDL that SQLAlchemy emits for them. Schema differences, migration history, DROP scripts, data export, database inspection, automatic model discovery, and table filtering are outside v1. Schema namespaces, extensions, and external database objects referenced by models remain prerequisites unless the metadata's creation hooks explicitly emit their creation DDL.

### Command and library interfaces

```text
sqlmodel-export TARGET --dialect {postgresql,sqlite,mysql} [--output PATH]
```

| Input | Contract |
|---|---|
| `TARGET` | Required `module.path:attribute.path`; examples: `myapp.models:SQLModel.metadata`, `myapp.models:Base.metadata`, `myapp.models:metadata`. |
| `--dialect` | Required, case-sensitive choice of `postgresql`, `sqlite`, or `mysql`. |
| `--output PATH` | Optional filesystem path. Omit it for stdout. Relative paths use the working directory. `.sql` is recommended but not enforced; `-` is a literal filename. |
| `--help` | Show syntax, supported dialects, and examples; exit successfully without importing models. |

Expose two small functions from `sqlmodel_export`:

```python
load_metadata(target: str) -> sqlalchemy.MetaData
export_ddl(metadata: sqlalchemy.MetaData, *, dialect: str) -> str
```

`load_metadata` resolves the target and validates its type and nonempty table collection. `export_ddl` repeats the type/nonempty checks for direct callers and returns the complete formatted SQL string. Neither library function writes SQL to an output destination. The CLI composes them and handles output. A single internal implementation serves the CLI and Python API.

### Import and metadata resolution

1. Require exactly one colon, a nonempty dotted module name, and a nonempty dotted attribute path. Each segment must be a Python identifier.
2. Import the module with `importlib.import_module`, using the interpreter's normal import search path. Resolve attributes successively with `getattr`; evaluate no expressions and invoke no target factories.
3. Require the final object to be an instance of `sqlalchemy.MetaData` and require at least one registered table.

Install the exporter in the application's Python environment and make the application package importable, preferably with an editable installation. A `src/` layout requires that installation or an explicitly configured Python import path; the exporter does not recursively scan directories or alter `sys.path`.

The target module must import every desired model module before resolution completes. SQLModel registers table definitions when the classes are defined; this is why importing only `SQLModel` is insufficient. The exporter can detect empty metadata, but cannot infer whether a nonempty collection is missing intended models. [SQLModel metadata ordering documentation](https://sqlmodel.tiangolo.com/tutorial/create-db-and-table/#sqlmodel-metadata-order-matters)

Imports and metadata event handlers execute trusted application Python code. Users provide importable model modules whose initialization works offline; the exporter supplies no database connection and cannot prevent application code from opening one. The CLI redirects ordinary Python stdout writes during loading and generation to stderr so model diagnostics do not contaminate SQL output. Application code that writes directly to file descriptors or launches subprocesses remains responsible for its own output. Library calls retain the caller's stream behavior.

### DDL generation

Follow SQLAlchemy's documented metadata export recipe: create a mock engine with a collecting executor and call `metadata.create_all(mock_engine, checkfirst=False)`. This obtains the metadata creation sequence rather than compiling each `CreateTable` independently. [SQLAlchemy metadata export recipe](https://docs.sqlalchemy.org/en/20/faq/metadata_schema.html#how-can-i-get-the-create-table-drop-table-output-as-a-string)

Map the three accepted dialect names to `postgresql://`, `sqlite://`, and `mysql://` respectively. Each URL selects a dialect for `create_mock_engine`; it contains no connection settings. For each callback, compile the received SQL expression using `sql.compile(dialect=mock_engine.dialect)` and collect its text. The mock engine is intended for DDL generation without result-bearing database queries; creation hooks must work within that contract. [Mock engine API](https://docs.sqlalchemy.org/en/20/core/engines.html#sqlalchemy.create_mock_engine)

Construct the mock engine with `create_mock_engine(url, executor, paramstyle="named")` for each supported dialect. This produces percent characters suitable for a SQL file rather than escaping them for DBAPI interpolation. Preserve percent-bearing identifiers, string defaults, modulo expressions, and intentional repeated percent characters through dialect configuration; keep the compiled SQL free of blanket percent replacements. [SQLAlchemy percent-escaping FAQ](https://docs.sqlalchemy.org/en/20/faq/sqlexpressions.html#why-are-percent-signs-being-doubled-up-when-stringifying-sql-statements)

Preserve callback order and emitted object definitions. SQLAlchemy handles foreign-key dependencies and, on PostgreSQL and MySQL, can emit separate `ALTER TABLE ... ADD CONSTRAINT` statements for cycles. Those statements belong to initial schema creation and are included in the export. SQLite retains its own dialect behavior and ALTER limitations. [Constraint creation and dependency cycles](https://docs.sqlalchemy.org/en/20/core/constraints.html#creating-dropping-foreign-key-constraints-via-alter)

PostgreSQL enum creation follows the models' configuration, including shared enum handling and `create_type=False`. An enum configured as externally managed remains an external prerequisite. [PostgreSQL ENUM API](https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#sqlalchemy.dialects.postgresql.ENUM)

For each compiled fragment, trim surrounding whitespace, require nonempty text, and append a semicolon if the fragment does not already end with one. Join fragments with one blank line and terminate the result with one newline. Preserve internal SQL whitespace and quoting. Treat each callback as a complete SQL fragment; custom DDL must provide syntactically complete SQL with any terminal semicolon after its last comment. Require at least one emitted fragment. Add no timestamps, headers, transaction wrappers, or existence guards. Preserve SQLAlchemy's ordering rather than promising byte-identical ordering across dependency versions or processes.

Dialect support means compiling metadata valid for that dialect. It does not translate vendor-specific types into portable substitutes or certify that every database server version can execute the result. Propagate compilation failures instead of omitting unsupported objects.

### Output and failures

Generate the entire SQL string before writing the selected destination. Memory use is proportional to the emitted DDL; streaming is outside v1 because output must remain untouched on generation failure.

For file output, require the parent directory to exist. After successful generation, write UTF-8 text with LF newlines to a temporary file in that directory, close it, and replace the destination with `os.replace`. Remove the temporary file if writing or replacement fails. Replacement applies to the named directory entry, including a symlink at that path; its referent is not overwritten. Existing file permissions and ownership are not preservation guarantees. Successful file output leaves stdout empty and requires no `--force` option. Filesystem errors produce failure without reporting export success.

For stdout, write and flush the complete string after generation. A downstream write failure may leave partial output, since stdout cannot be rolled back; report failure through the exit status.

| Condition | Behavior |
|---|---|
| Missing/unknown option, malformed target, unsupported dialect | CLI usage error on stderr; exit 2. Direct API calls reject invalid strings with `ValueError`. |
| Missing module or dependency; missing attribute | Fail at the import or attribute lookup and retain its specific exception and traceback on stderr; exit 1. |
| Resolved value is not `MetaData` | Raise `TypeError` identifying the target and actual type; CLI exits 1. |
| Empty metadata or empty generation | Raise `ValueError` explaining the unmet invariant and, for empty metadata, the need to import model definitions; CLI exits 1. |
| Model initialization, unresolved foreign key, unsupported type, DDL hook, or compiler failure | Propagate the original exception and traceback; CLI exits 1 for ordinary exceptions. Application `SystemExit` and interrupts retain Python behavior. |
| Output open/write/replace/flush failure | Report the original I/O exception on stderr; exit 1. |
| Successful export | Exit 0. |

Catch only exceptions needed for usage reporting, temporary-file cleanup, and output handling. Unexpected failures remain visible; the exporter returns no substitute SQL, retries no imports, and continues past no failed DDL object. SQLAlchemy warnings retain normal warning behavior on stderr.

---

## Implementation

### Step 1: Establish the standalone package and resolver

- [x] Create standalone package metadata, `src/sqlmodel_export/`, the console entry point, pytest configuration, and development dependencies. Set the declared Python/SQLAlchemy bounds and keep SQLModel in test dependencies only. <!-- completed: 2026-09-26T08:56 -->
- [x] Implement and test `load_metadata`: direct/nested attributes, plain SQLAlchemy and SQLModel fixtures, import registration across modules, malformed targets, missing dependencies/attributes, incorrect types, and empty metadata. <!-- completed: 2026-09-26T08:56 -->

### Step 2: Generate and deliver complete DDL

- [x] Implement and test `export_ddl` using the mock-engine callback and named paramstyle. Cover all three dialects with tables, indexes, primary/unique/check/foreign-key constraints and server defaults; cover PostgreSQL shared enums, externally managed enums, and PostgreSQL/MySQL cycles. Add PostgreSQL/MySQL regression cases preserving percent-bearing identifiers, string defaults, modulo check expressions, and intentional repeated percent characters. Verify SQLite's dialect behavior, statement delimiters, and propagation of unresolved references and compilation failures. <!-- completed: 2026-09-26T09:04 -->
- [x] Implement and test CLI parsing, stderr redirection during loading/generation, stdout emission, and temporary-file replacement. Verify stdout/file equality, replacement without `--force`, generation failure preserving existing files, failure cleanup, nonexistent parents, and nonzero status on output errors. <!-- completed: 2026-09-26T09:06 -->

### Step 3: Verify installation and document use

- [x] Run subprocess CLI tests from an installed wheel in isolated Python 3.14 environments with no Alembic or PostgreSQL/MySQL DBAPI drivers. Exercise core tests without SQLModel and compatibility tests with resolver-compatible SQLModel versions using the latest allowed SQLAlchemy 2.0 release. Verify ordinary model stdout goes to stderr and a late compilation failure produces no SQL output. <!-- completed: 2026-09-26T09:22 -->
- [x] Write a concise README with SQLAlchemy and SQLModel target examples, installation in the application's environment, complete model-import requirements, dialect limits, trusted import/hook behavior, and replacement semantics. Build and inspect the wheel and source distribution and run the full package test suite; publication remains a separately authorized action. <!-- completed: 2026-09-26T09:13 -->

## Changelog

| Date | Changes |
|------|---------|
| 2026-09-26 | Required src-layout and uv; narrowed execution validation to Python 3.14 at user request. Completed implementation with 117 passing checks and independent review approval; pushed branch and opened PR #1 with user approval. |
