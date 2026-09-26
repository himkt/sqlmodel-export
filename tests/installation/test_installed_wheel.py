import json
import os
from pathlib import Path
import subprocess

import pytest


@pytest.fixture(scope="module")
def wheel_python():
    configured = os.environ.get("SQLMODEL_EXPORT_WHEEL_PYTHON")
    if configured is None:
        pytest.skip("Set SQLMODEL_EXPORT_WHEEL_PYTHON to an isolated wheel environment's Python")
    interpreter = Path(configured)
    assert interpreter.is_absolute(), "Wheel environment interpreter must be an absolute path"
    assert interpreter.is_file(), "Wheel environment interpreter must exist"
    return interpreter


@pytest.fixture(scope="module")
def wheel_environment(wheel_python, tmp_path_factory):
    inspection = """
import importlib.metadata
import importlib.util
import json
import pathlib
import sysconfig
import sqlmodel_export
distribution = importlib.metadata.distribution("sqlmodel-export")
direct_url = distribution.read_text("direct_url.json")
print(json.dumps({
    "package": str(pathlib.Path(sqlmodel_export.__file__).resolve()),
    "purelib": str(pathlib.Path(sysconfig.get_path("purelib")).resolve()),
    "scripts": sysconfig.get_path("scripts"),
    "direct_url": json.loads(direct_url) if direct_url else None,
    "files": [str(path) for path in distribution.files],
    "dependencies": distribution.requires,
    "optional_modules": {name: importlib.util.find_spec(name) is not None for name in
        ["sqlmodel", "alembic", "psycopg", "psycopg2", "pg8000", "pymysql", "MySQLdb", "mariadb", "asyncpg", "aiomysql", "asyncmy"]},
}))
"""
    result = subprocess.run([str(wheel_python), "-I", "-c", inspection],
                            cwd=tmp_path_factory.mktemp("wheel-inspection"),
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    environment = json.loads(result.stdout)
    assert Path(environment["package"]).is_relative_to(Path(environment["purelib"]))
    assert "sqlmodel_export/__init__.py" in environment["files"]
    direct_url = environment["direct_url"]
    assert direct_url is None or not direct_url.get("dir_info", {}).get("editable", False)
    return environment


@pytest.fixture
def installed_cli(wheel_environment, tmp_path):
    script = Path(wheel_environment["scripts"]) / ("sqlmodel-export.exe" if os.name == "nt" else "sqlmodel-export")
    assert script.is_file(), "Wheel must install the sqlmodel-export console script"
    application = tmp_path / "application"
    application.mkdir()
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(application)
    environment.pop("PYTHONHOME", None)

    def invoke(source, arguments):
        (application / "wheel_models.py").write_text(source, encoding="utf-8")
        return subprocess.run([str(script), *arguments], cwd=tmp_path,
                              env=environment, capture_output=True, text=True)

    return invoke


MODEL_SOURCE = """
from sqlalchemy import Column, Integer, MetaData, Table, event
metadata = MetaData()
Table("widget", metadata, Column("id", Integer, primary_key=True))
print("import diagnostic")
event.listen(metadata, "after_create", lambda *args, **kwargs: print("hook diagnostic"))
"""


def test_core_wheel_environment_excludes_optional_database_packages(wheel_environment):
    assert not any(wheel_environment["optional_modules"].values()), wheel_environment["optional_modules"]
    runtime_dependencies = [requirement for requirement in wheel_environment["dependencies"] if "extra ==" not in requirement]
    assert len(runtime_dependencies) == 1
    assert runtime_dependencies[0].lower().startswith("sqlalchemy")


@pytest.mark.parametrize("dialect", ["postgresql", "sqlite", "mysql"])
def test_installed_console_exports_offline_to_stdout_and_file(installed_cli, tmp_path, dialect):
    arguments = ["wheel_models:metadata", "--dialect", dialect]
    printed = installed_cli(MODEL_SOURCE, arguments)
    assert printed.returncode == 0, printed.stderr
    assert printed.stdout.startswith("CREATE TABLE widget")
    assert "diagnostic" not in printed.stdout
    assert printed.stderr == "import diagnostic\nhook diagnostic\n"

    written = installed_cli(MODEL_SOURCE, [*arguments, "--output", "schema.sql"])
    assert written.returncode == 0, written.stderr
    assert written.stdout == ""
    assert written.stderr == printed.stderr
    assert (tmp_path / "schema.sql").read_bytes() == printed.stdout.encode("utf-8")


@pytest.mark.parametrize("file_output", [False, True])
def test_installed_console_buffers_sql_until_late_compilation_succeeds(installed_cli, tmp_path, file_output):
    source = MODEL_SOURCE + """
from sqlalchemy.dialects.postgresql import JSONB
Table("zzz_invalid", metadata, Column("payload", JSONB))
"""
    destination = tmp_path / "schema.sql"
    destination.write_bytes(b"existing schema\n")
    arguments = ["wheel_models:metadata", "--dialect", "sqlite"]
    if file_output:
        arguments += ["--output", "schema.sql"]
    result = installed_cli(source, arguments)
    assert result.returncode == 1
    assert result.stdout == ""
    assert "import diagnostic" in result.stderr
    assert "Traceback" in result.stderr
    assert "CompileError" in result.stderr
    assert "zzz_invalid" in result.stderr
    assert destination.read_bytes() == b"existing schema\n"


def test_installed_console_help_works_without_models(installed_cli):
    result = installed_cli('raise RuntimeError("unexpected import")\n', ["--help"])
    assert result.returncode == 0
    assert result.stderr == ""
    assert "--dialect" in result.stdout
    assert "postgresql" in result.stdout
