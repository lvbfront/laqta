"""Fixtures for the server tests.

Two things differ from the rest of the suite, both because of the same fact:
the server opens its own database connections and commits through them.

`tests/conftest.py`'s `db_session` wraps each test in a transaction and rolls
it back, which is exactly right for code that is handed a Session. It does not
reach a connection the code opened for itself. So the server tests get a
database that is truncated and re-seeded around each test instead — the same
thing `eval/database.py` does between episodes, and for the same reason.

The `engine` fixture is imported rather than redefined: it owns the rule that
refuses to wipe a database whose name does not end in `_test`, and a second
copy of that rule is a second chance to get it wrong.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import sessionmaker

from tests.conftest import db_session, engine, policy  # noqa: F401 — fixtures


@pytest.fixture()
def sessions(engine):  # noqa: F811
    """A factory for short-lived sessions that commit, for asserting on what
    the server actually wrote."""
    return sessionmaker(bind=engine, autoflush=False)


@pytest.fixture()
def seeded(engine, sessions):  # noqa: F811
    """The seed data, committed, and cleaned up afterwards.

    Committed because the server cannot see an open transaction it is not
    part of; cleaned up because nothing else will, and `contacts.id` 1 has to
    be أحمد العتيبي in every test that names him.
    """
    from datetime import datetime, timezone

    from app.config import get_policy
    from scripts import seed as seed_script

    def wipe() -> None:
        with sessions() as db:
            seed_script.reset(db)
            db.commit()

    wipe()
    with sessions() as db:
        seed_script.seed(db, now=datetime.now(timezone.utc), policy=get_policy())
        db.commit()
    yield
    wipe()
