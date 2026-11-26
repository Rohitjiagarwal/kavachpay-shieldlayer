import os
import tempfile

import pytest

# isolate the DB per test session and force offline providers
os.environ.setdefault("APP_DB", os.path.join(tempfile.gettempdir(), "shieldlayer_pytest.db"))
os.environ.setdefault("CHAT_PROVIDER", "stub")
os.environ["LAYER2_PROVIDER"] = "heuristic"
# Safety net: any Gemini call a test makes by mistake goes to a dead local port,
# never to Google, so the real key in .env can't be spent by the test suite.
os.environ["GEMINI_BASE_URL"] = "http://127.0.0.1:9/no-network-in-tests"


@pytest.fixture(scope="session", autouse=True)
def seeded():
    # fresh DB + KB for the whole test session
    if os.path.exists(os.environ["APP_DB"]):
        os.remove(os.environ["APP_DB"])
    from app import seed

    seed.reset_data()
    seed.ingest_kb()
    yield
