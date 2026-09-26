import os
import subprocess
import sys

import pytest


MODEL_SOURCE = """
from sqlalchemy import Column, Integer, MetaData, Table, event
metadata = MetaData()
Table("widget", metadata, Column("id", Integer, primary_key=True))
"""


@pytest.fixture
def run_cli(tmp_path):
    def run(arguments, source=MODEL_SOURCE, prelude=""):
        (tmp_path / "cli_models.py").write_text(source, encoding="utf-8")
        environment = os.environ.copy()
        environment["PYTHONPATH"] = os.pathsep.join(str(path) for path in sys.path if path)
        script = prelude + """
import sys
from sqlmodel_export.cli import main
try:
    status = main()
finally:
    sys.stdout = sys.__stdout__
raise SystemExit(status)
"""
        return subprocess.run([sys.executable, "-c", script, *arguments], cwd=tmp_path,
                              env=environment, capture_output=True, text=True)

    return run


@pytest.mark.parametrize("arguments", [
    [], ["cli_models:metadata"], ["--dialect", "sqlite"],
    ["cli_models:metadata", "--dialect", "oracle"],
    ["cli_models:metadata", "--dialect", "SQLite"],
    ["cli_models:metadata", "--dialect", "sqlite", "--unknown"],
    ["cli_models:metadata", "--dialect", "sqlite", "--output"],
    ["cli_models.metadata", "--dialect", "sqlite"],
    ["cli_models:metadata()", "--dialect", "sqlite"],
])
def test_usage_errors_exit_two_without_import_or_sql(run_cli, arguments):
    result = run_cli(arguments, source='raise AssertionError("model was imported")\n')
    assert result.returncode == 2
    assert result.stdout == ""
    assert "usage:" in result.stderr.lower()
    assert "AssertionError" not in result.stderr


def test_help_explains_dialects_and_examples_without_import(run_cli):
    result = run_cli(["--help"], source='raise AssertionError("model was imported")\n')
    assert result.returncode == 0
    assert result.stderr == ""
    for token in ["TARGET", "postgresql", "sqlite", "mysql", "--output", ":", "example"]:
        assert token.lower() in result.stdout.lower()


@pytest.mark.parametrize("dialect", ["postgresql", "sqlite", "mysql"])
def test_stdout_and_file_output_are_identical_and_replace_existing_file(run_cli, tmp_path, dialect):
    arguments = ["cli_models:metadata", "--dialect", dialect]
    standard = run_cli(arguments)
    assert standard.returncode == 0, standard.stderr
    assert "CREATE TABLE widget" in standard.stdout
    assert standard.stderr == ""
    destination = tmp_path / "schema.data"
    destination.write_text("old contents", encoding="utf-8")

    written = run_cli([*arguments, "--output", "schema.data"])

    assert written.returncode == 0, written.stderr
    assert written.stdout == ""
    assert destination.read_bytes() == standard.stdout.encode("utf-8")
    assert b"\r" not in destination.read_bytes()
    assert {path.name for path in tmp_path.iterdir()} <= {"cli_models.py", "__pycache__", "schema.data"}


def test_output_dash_is_literal_filename(run_cli, tmp_path):
    result = run_cli(["cli_models:metadata", "--dialect", "sqlite", "--output", "-"])
    assert result.returncode == 0, result.stderr
    assert result.stdout == ""
    assert "CREATE TABLE widget" in (tmp_path / "-").read_text(encoding="utf-8")


def test_file_output_uses_utf8_encoding(run_cli, tmp_path):
    source = MODEL_SOURCE.replace('"widget"', '"café"')
    result = run_cli(["cli_models:metadata", "--dialect", "sqlite", "--output", "schema.sql"], source=source)
    assert result.returncode == 0, result.stderr
    assert 'CREATE TABLE "café"' in (tmp_path / "schema.sql").read_bytes().decode("utf-8")


def test_import_and_hook_stdout_are_redirected_to_stderr(run_cli):
    result = run_cli(["cli_models:metadata", "--dialect", "sqlite"], source=MODEL_SOURCE + """
print("import diagnostic")
event.listen(metadata, "after_create", lambda *args, **kwargs: print("hook diagnostic"))
""")
    assert result.returncode == 0, result.stderr
    assert "CREATE TABLE widget" in result.stdout
    assert "diagnostic" not in result.stdout
    assert result.stderr == "import diagnostic\nhook diagnostic\n"


@pytest.mark.parametrize("source, exception", [
    ("import nonexistent_cli_dependency\n", "ModuleNotFoundError"),
    ("value = 1\n", "AttributeError"),
    ("metadata = 1\n", "TypeError"),
    ("from sqlalchemy import MetaData\nmetadata = MetaData()\n", "ValueError"),
    ('raise RuntimeError("model initialization failed")\n', "RuntimeError"),
    (MODEL_SOURCE + '\ndef fail(*args, **kwargs):\n    raise RuntimeError("late hook failure")\nevent.listen(metadata, "after_create", fail)\n', "RuntimeError"),
    (MODEL_SOURCE + '\nfrom sqlalchemy.dialects.postgresql import JSONB\nTable("zzz_unsupported", metadata, Column("payload", JSONB))\n', "CompileError"),
])
@pytest.mark.parametrize("file_output", [False, True])
def test_generation_failure_emits_no_sql_and_preserves_destination(run_cli, tmp_path, source, exception, file_output):
    destination = tmp_path / "schema.sql"
    destination.write_bytes(b"existing schema\n")
    arguments = ["cli_models:metadata", "--dialect", "sqlite"]
    if file_output:
        arguments += ["--output", str(destination)]
    result = run_cli(arguments, source=source)
    assert result.returncode == 1
    assert result.stdout == ""
    assert "Traceback" in result.stderr
    assert exception in result.stderr
    assert destination.read_bytes() == b"existing schema\n"
    assert {path.name for path in tmp_path.iterdir()} <= {"cli_models.py", "__pycache__", "schema.sql"}


def test_missing_target_module_retains_traceback(run_cli):
    result = run_cli(["nonexistent_cli_models:metadata", "--dialect", "sqlite"])
    assert result.returncode == 1
    assert result.stdout == ""
    assert "ModuleNotFoundError" in result.stderr
    assert "Traceback" in result.stderr


def test_application_system_exit_retains_exit_code(run_cli):
    result = run_cli(["cli_models:metadata", "--dialect", "sqlite"], source="raise SystemExit(7)\n")
    assert result.returncode == 7
    assert result.stdout == ""


def test_missing_output_parent_fails_without_creating_directories(run_cli, tmp_path):
    result = run_cli(["cli_models:metadata", "--dialect", "sqlite", "--output", "missing/schema.sql"])
    assert result.returncode == 1
    assert "FileNotFoundError" in result.stderr
    assert result.stdout == ""
    assert not (tmp_path / "missing").exists()


def test_symlink_output_replaces_link_and_preserves_referent(run_cli, tmp_path):
    referent = tmp_path / "referent.sql"
    referent.write_text("original", encoding="utf-8")
    destination = tmp_path / "schema.sql"
    destination.symlink_to(referent)
    result = run_cli(["cli_models:metadata", "--dialect", "sqlite", "--output", "schema.sql"])
    assert result.returncode == 0, result.stderr
    assert not destination.is_symlink()
    assert "CREATE TABLE widget" in destination.read_text(encoding="utf-8")
    assert referent.read_text(encoding="utf-8") == "original"


def test_replace_uses_complete_temp_file_in_destination_directory_and_cleans_failure(run_cli, tmp_path):
    destination = tmp_path / "schema.sql"
    destination.write_text("original", encoding="utf-8")
    prelude = """
import os
from pathlib import Path
def fail_replace(source, destination):
    source, destination = Path(source), Path(destination)
    assert source.resolve().parent == destination.resolve().parent
    assert source.resolve() != destination.resolve()
    assert "CREATE TABLE widget" in source.read_text(encoding="utf-8")
    raise PermissionError("injected replacement failure")
os.replace = fail_replace
"""
    result = run_cli(["cli_models:metadata", "--dialect", "sqlite", "--output", "schema.sql"], prelude=prelude)
    assert result.returncode == 1
    assert "PermissionError: injected replacement failure" in result.stderr
    assert result.stdout == ""
    assert destination.read_text(encoding="utf-8") == "original"
    assert {path.name for path in tmp_path.iterdir()} <= {"cli_models.py", "__pycache__", "schema.sql"}


@pytest.mark.parametrize("operation", ["write", "flush"])
def test_stdout_failure_has_nonzero_status_and_original_error(run_cli, operation):
    prelude = f"""
import io
import sys
class FailingOutput(io.StringIO):
    def {operation}(self, *args, **kwargs):
        raise OSError("injected stdout {operation} failure")
sys.stdout = FailingOutput()
"""
    result = run_cli(["cli_models:metadata", "--dialect", "sqlite"], prelude=prelude)
    assert result.returncode != 0
    assert f"OSError: injected stdout {operation} failure" in result.stderr


def test_file_write_failure_cleans_temporary_file_and_preserves_destination(run_cli, tmp_path):
    destination = tmp_path / "schema.sql"
    destination.write_text("original", encoding="utf-8")
    prelude = """
import builtins
import io
import os
class FailingFile:
    def __init__(self, stream):
        self.stream = stream
    def __getattr__(self, name):
        return getattr(self.stream, name)
    def __enter__(self):
        self.stream.__enter__()
        return self
    def __exit__(self, *args):
        return self.stream.__exit__(*args)
    def write(self, value):
        raise OSError("injected file write failure")
def wrap_open(original):
    def open_file(*args, **kwargs):
        stream = original(*args, **kwargs)
        mode = kwargs.get("mode", args[1] if len(args) > 1 else "r")
        return FailingFile(stream) if "w" in mode else stream
    return open_file
builtins.open = wrap_open(builtins.open)
io.open = wrap_open(io.open)
os.fdopen = wrap_open(os.fdopen)
"""
    result = run_cli(["cli_models:metadata", "--dialect", "sqlite", "--output", "schema.sql"], prelude=prelude)
    assert result.returncode == 1
    assert "OSError: injected file write failure" in result.stderr
    assert result.stdout == ""
    assert destination.read_text(encoding="utf-8") == "original"
    assert {path.name for path in tmp_path.iterdir()} <= {"cli_models.py", "__pycache__", "schema.sql"}
