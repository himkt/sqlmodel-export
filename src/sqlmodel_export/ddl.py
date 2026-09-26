from sqlalchemy import MetaData, create_mock_engine

from .metadata import validate_metadata


DIALECT_URLS = {
    "postgresql": "postgresql://",
    "sqlite": "sqlite://",
    "mysql": "mysql://",
}


def export_ddl(metadata: MetaData, *, dialect: str) -> str:
    validate_metadata(metadata, label="Metadata")
    if dialect not in DIALECT_URLS:
        raise ValueError(f"Unsupported dialect {dialect!r}; choose from {', '.join(DIALECT_URLS)}")
    fragments: list[str] = []

    def collect(sql, *multiparams, **params):
        fragment = str(sql.compile(dialect=engine.dialect)).strip()
        if not fragment:
            raise ValueError("DDL compilation emitted an empty fragment")
        fragments.append(fragment if fragment.endswith(";") else fragment + ";")

    engine = create_mock_engine(DIALECT_URLS[dialect], collect, paramstyle="named")
    metadata.create_all(engine, checkfirst=False)
    if not fragments:
        raise ValueError("Metadata creation emitted no DDL fragments")
    return "\n\n".join(fragments) + "\n"
