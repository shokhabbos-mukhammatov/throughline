import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.environ.setdefault("THROUGHLINE_OFFLINE", "1")
os.environ.setdefault("PERSIST", "0")
os.environ.setdefault("BULLETIN_LIVE", "0")

from throughline.config import Settings  # noqa: E402
from throughline.ctx import Ctx  # noqa: E402
from throughline.llm.offline import OfflineEngine  # noqa: E402
from throughline.store.memory import MemoryStore  # noqa: E402


@pytest.fixture
def ctx(tmp_path):
    settings = Settings(offline=True, persist=False, data_dir=str(tmp_path), bulletin_live=False)
    return Ctx(store=MemoryStore(), engine=OfflineEngine(), settings=settings)
