import importlib

from sqlalchemy import MetaData


def parse_target(target: str) -> tuple[str, list[str]]:
    if target.count(":") != 1:
        raise ValueError("Target must have the form module.path:attribute.path")
    module_name, attribute_path = target.split(":")
    attributes = attribute_path.split(".")
    if not all(part.isidentifier() for part in [*module_name.split("."), *attributes]):
        raise ValueError("Target module and attribute paths must contain Python identifiers")
    return module_name, attributes


def validate_metadata(value: object, *, label: str) -> MetaData:
    if not isinstance(value, MetaData):
        raise TypeError(f"{label} must be sqlalchemy.MetaData; got {type(value).__name__}")
    if not value.tables:
        raise ValueError(f"{label} has no tables; import model definitions before exporting")
    return value


def load_metadata(target: str) -> MetaData:
    module_name, attributes = parse_target(target)
    value = importlib.import_module(module_name)
    for attribute in attributes:
        value = getattr(value, attribute)
    return validate_metadata(value, label=f"Target {target!r}")
