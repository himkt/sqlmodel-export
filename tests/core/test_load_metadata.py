import importlib
import sys
from types import SimpleNamespace

import pytest
from sqlalchemy import Column, Integer, MetaData, Table


MODEL_SOURCE = """
from types import SimpleNamespace
from sqlalchemy import Column, Integer, MetaData, Table
metadata = MetaData()
Table("widget", metadata, Column("id", Integer, primary_key=True))
Base = SimpleNamespace(metadata=metadata)
registry = SimpleNamespace(Base=Base)
"""


@pytest.mark.parametrize("attribute", ["metadata", "Base.metadata", "registry.Base.metadata"])
def test_resolves_direct_and_nested_metadata(load_metadata, model_modules, attribute):
    name = model_modules("resolver_app.models", MODEL_SOURCE)
    expected = importlib.import_module(name).metadata
    original_path = sys.path.copy()

    assert load_metadata(f"{name}:{attribute}") is expected
    assert set(expected.tables) == {"widget"}
    assert sys.path == original_path


def test_imports_model_definitions_registered_in_other_modules(load_metadata, model_modules):
    model_modules("registration_app.base", "from sqlalchemy import MetaData\nmetadata = MetaData()\n")
    model_modules("registration_app.tables", """
from sqlalchemy import Column, Integer, Table
from .base import metadata
Table("registered", metadata, Column("id", Integer, primary_key=True))
""")
    name = model_modules("registration_app.models", "from .base import metadata\nfrom . import tables\n")

    assert set(load_metadata(f"{name}:metadata").tables) == {"registered"}


@pytest.mark.parametrize("target", [
    "", "models", "models:", ":metadata", "models:metadata:extra",
    ".models:metadata", "models.:metadata", "models..tables:metadata",
    "models:.metadata", "models:metadata.", "models:Base..metadata",
    "my-models:metadata", "1models:metadata", "models:1metadata",
    " models:metadata", "models:metadata ", "models:metadata()",
    "models:registry['metadata']", "models/path:metadata", "models:meta-data",
])
def test_rejects_malformed_target_before_import(load_metadata, monkeypatch, target):
    def unexpected_import(*args, **kwargs):
        pytest.fail("Malformed targets must be rejected before importing application code")

    monkeypatch.setattr(importlib, "import_module", unexpected_import)
    with pytest.raises(ValueError):
        load_metadata(target)


def test_accepts_unicode_python_identifiers(load_metadata, monkeypatch):
    metadata = MetaData()
    Table("widget", metadata, Column("id", Integer))
    module = SimpleNamespace(данные=metadata)
    monkeypatch.setitem(sys.modules, "модели", module)

    assert load_metadata("модели:данные") is metadata


def test_missing_module_retains_module_not_found_error(load_metadata):
    with pytest.raises(ModuleNotFoundError) as caught:
        load_metadata("sqlmodel_export_nonexistent_application:metadata")
    assert caught.value.name == "sqlmodel_export_nonexistent_application"


def test_missing_dependency_retains_dependency_name(load_metadata, model_modules):
    name = model_modules("dependency_app.models", "import sqlmodel_export_nonexistent_dependency\n")
    with pytest.raises(ModuleNotFoundError) as caught:
        load_metadata(f"{name}:metadata")
    assert caught.value.name == "sqlmodel_export_nonexistent_dependency"


@pytest.mark.parametrize("attribute", ["missing", "Base.missing", "registry.missing.metadata"])
def test_missing_attribute_retains_attribute_error(load_metadata, model_modules, attribute):
    name = model_modules("attribute_app.models", MODEL_SOURCE)
    with pytest.raises(AttributeError, match="missing"):
        load_metadata(f"{name}:{attribute}")


@pytest.mark.parametrize("expression, type_name", [("None", "NoneType"), ("42", "int"), ("{}", "dict")])
def test_wrong_type_identifies_target_and_actual_type(load_metadata, model_modules, expression, type_name):
    name = model_modules("wrong_type_app.models", f"value = {expression}\n")
    target = f"{name}:value"
    with pytest.raises(TypeError) as caught:
        load_metadata(target)
    assert target in str(caught.value)
    assert type_name in str(caught.value)


def test_target_factory_is_validated_without_being_called(load_metadata, model_modules):
    name = model_modules("factory_app.models", """
def metadata():
    raise AssertionError("Target factory was invoked")
""")
    with pytest.raises(TypeError, match="function"):
        load_metadata(f"{name}:metadata")


def test_empty_metadata_explains_model_import_requirement(load_metadata, model_modules):
    name = model_modules("empty_app.models", "from sqlalchemy import MetaData\nmetadata = MetaData()\n")
    with pytest.raises(ValueError) as caught:
        load_metadata(f"{name}:metadata")
    message = str(caught.value).lower()
    assert "import" in message
    assert "model" in message


@pytest.mark.parametrize("exception", [RuntimeError("initialization failed"), SystemExit(7), KeyboardInterrupt()])
def test_import_exception_propagates_unchanged_without_retry(load_metadata, monkeypatch, exception):
    attempts = []

    def failing_import(name):
        attempts.append(name)
        raise exception

    monkeypatch.setattr(importlib, "import_module", failing_import)
    with pytest.raises(type(exception)) as caught:
        load_metadata("failing_app:metadata")
    assert caught.value is exception
    assert attempts == ["failing_app"]


def test_library_preserves_import_stdout(load_metadata, model_modules, capsys):
    name = model_modules("printing_app.models", MODEL_SOURCE + '\nprint("model diagnostic")\n')
    load_metadata(f"{name}:metadata")
    captured = capsys.readouterr()
    assert captured.out == "model diagnostic\n"
    assert captured.err == ""
