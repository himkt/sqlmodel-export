import importlib

import pytest


pytest.importorskip("sqlmodel")


def test_sqlmodel_metadata_registers_imported_models(load_metadata, model_modules):
    model_modules("sqlmodel_compat_app.base", """
from sqlalchemy import MetaData
from sqlmodel import SQLModel
class AppModel(SQLModel):
    metadata = MetaData()
""")
    model_modules("sqlmodel_compat_app.tables", """
from sqlmodel import Field
from .base import AppModel
class Widget(AppModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
""")
    name = model_modules("sqlmodel_compat_app.models", "from .base import AppModel\nfrom . import tables\n")

    metadata = load_metadata(f"{name}:AppModel.metadata")

    assert metadata is importlib.import_module(name).AppModel.metadata
    assert set(metadata.tables) == {"widget"}


def test_sqlmodel_without_imported_table_definitions_is_empty(load_metadata, model_modules):
    name = model_modules("sqlmodel_empty_app.models", """
from sqlalchemy import MetaData
from sqlmodel import SQLModel
class AppModel(SQLModel):
    metadata = MetaData()
""")
    with pytest.raises(ValueError, match="(?i)import"):
        load_metadata(f"{name}:AppModel.metadata")


@pytest.mark.parametrize("dialect", ["postgresql", "sqlite", "mysql"])
def test_sqlmodel_metadata_exports_through_public_api(load_metadata, model_modules, dialect):
    from sqlmodel_export import export_ddl

    name = model_modules(f"sqlmodel_export_compat_{dialect}.models", """
from sqlalchemy import MetaData
from sqlmodel import Field, SQLModel
class AppModel(SQLModel):
    metadata = MetaData()
class Widget(AppModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(max_length=40, index=True)
""")
    metadata = load_metadata(f"{name}:AppModel.metadata")
    sql = export_ddl(metadata, dialect=dialect)
    assert "CREATE TABLE widget" in sql
    assert "PRIMARY KEY (id)" in sql
    assert "CREATE INDEX ix_widget_name ON widget (name)" in sql
