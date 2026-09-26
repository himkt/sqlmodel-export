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
