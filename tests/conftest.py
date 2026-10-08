import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def pytest_configure(config):
    # pytest.ini sets --basetemp=work/pytest (inside the repo, never /tmp); make sure its parent exists.
    (ROOT / "work").mkdir(exist_ok=True)
