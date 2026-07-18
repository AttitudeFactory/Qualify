"""Local SQLite engine for the mentions dashboard MVP.

`reflex.Model`/`rx.session()` are deprecated as of Reflex 0.9.2 (removed in
1.0), so this talks to SQLModel/SQLAlchemy directly instead.
"""

from contextlib import contextmanager
from typing import Iterator

from sqlmodel import Session, SQLModel, create_engine

engine = create_engine("sqlite:///reflex.db")


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)


@contextmanager
def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
