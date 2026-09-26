import sqlite3

import pytest
from sqlalchemy import (
    CheckConstraint, Column, DDL, ForeignKey, Index, Integer, MetaData,
    String, Table, UniqueConstraint, event, text,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.exc import CompileError, NoReferencedTableError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.schema import DDLElement


@pytest.fixture
def export_ddl():
    from sqlmodel_export import export_ddl

    return export_ddl


def simple_metadata():
    metadata = MetaData()
    Table("widget", metadata, Column("id", Integer, primary_key=True))
    return metadata


@pytest.mark.parametrize("dialect, identity", [
    ("postgresql", "SERIAL"), ("sqlite", "INTEGER"), ("mysql", "AUTO_INCREMENT"),
])
def test_emits_tables_constraints_indexes_defaults_in_dependency_order(export_ddl, dialect, identity):
    metadata = MetaData()
    Table("child", metadata, Column("id", Integer, primary_key=True),
          Column("parent_id", Integer, ForeignKey("parent.id")),
          Column("name", String(40), nullable=False, server_default=text("'new'")),
          UniqueConstraint("name", name="uq_child_name"),
          CheckConstraint("id > 0", name="ck_child_positive"))
    Table("parent", metadata, Column("id", Integer, primary_key=True))
    Index("ix_child_parent", metadata.tables["child"].c.parent_id)

    sql = export_ddl(metadata, dialect=dialect)

    assert sql.index("CREATE TABLE parent") < sql.index("CREATE TABLE child")
    assert identity in sql
    assert "PRIMARY KEY (id)" in sql
    assert "CONSTRAINT uq_child_name UNIQUE (name)" in sql
    assert "CONSTRAINT ck_child_positive CHECK (id > 0)" in sql
    assert "FOREIGN KEY(parent_id) REFERENCES parent (id)" in sql
    assert "DEFAULT 'new'" in sql
    assert "NOT NULL" in sql
    assert "CREATE INDEX ix_child_parent ON child (parent_id)" in sql
    assert "IF NOT EXISTS" not in sql
    assert "DROP " not in sql
    if dialect == "sqlite":
        with sqlite3.connect(":memory:") as connection:
            connection.executescript(sql)
            assert connection.execute("PRAGMA foreign_key_list(child)").fetchone()[2] == "parent"


def test_postgresql_shared_enum_is_created_once_before_both_tables(export_ddl):
    metadata = MetaData()
    status = ENUM("new", "done", name="status", metadata=metadata)
    for name in ("first", "second"):
        Table(name, metadata, Column("state", status))

    sql = export_ddl(metadata, dialect="postgresql")

    assert sql.count("CREATE TYPE status AS ENUM ('new', 'done')") == 1
    assert sql.index("CREATE TYPE") < sql.index("CREATE TABLE first")
    assert sql.count("state status") == 2


def test_postgresql_externally_managed_enum_remains_a_reference(export_ddl):
    metadata = MetaData()
    Table("widget", metadata, Column("state", ENUM("new", "done", name="status", create_type=False)))
    sql = export_ddl(metadata, dialect="postgresql")
    assert "state status" in sql
    assert "CREATE TYPE" not in sql


@pytest.mark.parametrize("dialect", ["postgresql", "mysql", "sqlite"])
def test_cyclic_foreign_keys_follow_dialect_creation_behavior(export_ddl, dialect):
    metadata = MetaData()
    Table("first", metadata, Column("id", Integer, primary_key=True),
          Column("second_id", Integer, ForeignKey("second.id", name="fk_first_second")))
    Table("second", metadata, Column("id", Integer, primary_key=True),
          Column("first_id", Integer, ForeignKey("first.id", name="fk_second_first")))

    sql = export_ddl(metadata, dialect=dialect)

    assert "CONSTRAINT fk_first_second FOREIGN KEY(second_id) REFERENCES second (id)" in sql
    assert "CONSTRAINT fk_second_first FOREIGN KEY(first_id) REFERENCES first (id)" in sql
    if dialect == "sqlite":
        assert "ALTER TABLE" not in sql
        with sqlite3.connect(":memory:") as connection:
            connection.executescript(sql)
    else:
        assert sql.count("ALTER TABLE") == 2
        assert sql.index("ALTER TABLE") > sql.index("CREATE TABLE first")
        assert sql.index("ALTER TABLE") > sql.index("CREATE TABLE second")


@pytest.mark.parametrize("dialect, quote", [("postgresql", '"'), ("mysql", "`")])
def test_percent_identifiers_defaults_and_modulo_preserve_exact_characters(export_ddl, dialect, quote):
    metadata = MetaData()
    table = Table("rate%table%%", metadata, Column("value%field%%", Integer),
          Column("label", String(40), server_default=text("'50% and 100%%'")),
          Column("quantity", Integer), CheckConstraint("quantity % 3 = 0", name="ck_mod"))
    table.append_constraint(CheckConstraint(table.c.quantity % 4 == 0, name="ck_expression_mod"))

    sql = export_ddl(metadata, dialect=dialect)

    assert f"{quote}rate%table%%{quote}" in sql
    assert f"{quote}value%field%%{quote}" in sql
    assert "DEFAULT '50% and 100%%'" in sql
    assert "CHECK (quantity % 3 = 0)" in sql
    assert "CHECK (quantity % 4 = 0)" in sql


def test_fragments_preserve_callback_order_internal_whitespace_and_semicolons(export_ddl):
    metadata = simple_metadata()
    event.listen(metadata, "before_create", DDL("  SELECT  1;  \n"))
    event.listen(metadata, "after_create", DDL("\n SELECT  2 /* final comment */; \n"))
    sql = export_ddl(metadata, dialect="sqlite")
    fragments = sql.rstrip("\n").split(";\n\n")
    assert len(fragments) == 3
    assert fragments[0] == "SELECT  1"
    assert fragments[1].startswith("CREATE TABLE widget (")
    assert fragments[2] == "SELECT  2 /* final comment */;"
    assert sql.endswith(";\n")
    assert not sql.endswith("\n\n")


@pytest.mark.parametrize("value", [None, {}, "metadata"])
def test_direct_api_requires_metadata_instance(export_ddl, value):
    with pytest.raises(TypeError):
        export_ddl(value, dialect="sqlite")


def test_direct_api_requires_registered_tables(export_ddl):
    with pytest.raises(ValueError) as caught:
        export_ddl(MetaData(), dialect="sqlite")
    assert "import" in str(caught.value).lower()
    assert "model" in str(caught.value).lower()


@pytest.mark.parametrize("dialect", ["", "PostgreSQL", "oracle", "sqlite://"])
def test_direct_api_rejects_unsupported_dialect(export_ddl, dialect):
    with pytest.raises(ValueError):
        export_ddl(simple_metadata(), dialect=dialect)


def test_empty_compiled_fragment_fails(export_ddl):
    metadata = simple_metadata()
    event.listen(metadata, "after_create", DDL(" \n\t "))
    with pytest.raises(ValueError):
        export_ddl(metadata, dialect="sqlite")


def test_metadata_emitting_no_fragments_fails(export_ddl):
    class SilentMetadata(MetaData):
        def create_all(self, bind, tables=None, checkfirst=True):
            pass

    metadata = SilentMetadata()
    Table("widget", metadata, Column("id", Integer))
    with pytest.raises(ValueError):
        export_ddl(metadata, dialect="sqlite")


def test_unresolved_foreign_key_propagates(export_ddl):
    metadata = MetaData()
    Table("widget", metadata, Column("parent", Integer, ForeignKey("missing.id")))
    with pytest.raises(NoReferencedTableError):
        export_ddl(metadata, dialect="sqlite")


@pytest.mark.parametrize("dialect", ["sqlite", "mysql"])
def test_unsupported_vendor_type_propagates_compilation_failure(export_ddl, dialect):
    metadata = MetaData()
    Table("widget", metadata, Column("payload", JSONB))
    with pytest.raises(CompileError):
        export_ddl(metadata, dialect=dialect)


def test_hook_exception_propagates_unchanged(export_ddl):
    metadata = simple_metadata()
    error = RuntimeError("hook failed")

    def fail(*args, **kwargs):
        raise error

    event.listen(metadata, "after_create", fail)
    with pytest.raises(RuntimeError) as caught:
        export_ddl(metadata, dialect="sqlite")
    assert caught.value is error


def test_compiler_exception_propagates_unchanged(export_ddl):
    class FailingDDL(DDLElement):
        pass

    error = RuntimeError("custom compiler failed")

    @compiles(FailingDDL)
    def compile_failure(element, compiler, **kwargs):
        raise error

    metadata = simple_metadata()
    event.listen(metadata, "after_create", FailingDDL())
    with pytest.raises(RuntimeError) as caught:
        export_ddl(metadata, dialect="sqlite")
    assert caught.value is error


def test_library_retains_hook_stdout_and_returns_sql_without_printing_it(export_ddl, capsys):
    metadata = simple_metadata()
    event.listen(metadata, "after_create", lambda *args, **kwargs: print("hook diagnostic"))
    sql = export_ddl(metadata, dialect="sqlite")
    assert "CREATE TABLE widget" in sql
    assert capsys.readouterr().out == "hook diagnostic\n"
