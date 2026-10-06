import copy
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCHEDULE = ROOT / "data" / "schedule.json"


@pytest.fixture
def schedule() -> dict:
    return copy.deepcopy(json.loads(SCHEDULE.read_text(encoding="utf-8")))
