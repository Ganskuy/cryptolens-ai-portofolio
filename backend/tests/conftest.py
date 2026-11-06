import os
import tempfile

# Isolated temporary SQLite schema: never points at a live project database.
TEST_DIR = tempfile.TemporaryDirectory(prefix="cryptolens-tests-")
os.environ["DATABASE_URL"] = "sqlite:///" + TEST_DIR.name + "/test.db"
os.environ["DATA_MODE"] = "fixture"
os.environ["AI_ENABLED"] = "false"
os.environ["OPENROUTER_API_KEY"] = ""

import pytest  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.worker import fixtures  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def database():
    Base.metadata.create_all(engine)
    fixtures()
    yield
    engine.dispose()
    TEST_DIR.cleanup()
