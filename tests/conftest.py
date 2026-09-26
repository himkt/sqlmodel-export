import importlib
import sys
import pytest


@pytest.fixture
def model_modules(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(tmp_path))
    module_names = set()

    def write_module(name, source):
        module_names.add(name.split(".")[0])
        path = tmp_path.joinpath(*name.split(".")).with_suffix(".py")
        path.parent.mkdir(parents=True, exist_ok=True)
        for parent in path.parents:
            if parent == tmp_path:
                break
            (parent / "__init__.py").touch()
        path.write_text(source, encoding="utf-8")
        importlib.invalidate_caches()
        return name

    yield write_module

    for name in tuple(sys.modules):
        if name.split(".")[0] in module_names:
            del sys.modules[name]


@pytest.fixture
def load_metadata():
    from sqlmodel_export import load_metadata

    return load_metadata
