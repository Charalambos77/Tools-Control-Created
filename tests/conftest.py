import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "sdk"))


@pytest.fixture()
def demo(tmp_path, monkeypatch):
    """A fresh pretend ~/.claude (chats, skills, plugin, MCP servers) in a temp folder."""
    monkeypatch.setenv("TC_DEMO", "1")
    monkeypatch.setenv("TC_DATA", str(tmp_path))
    from tctl import store
    monkeypatch.setattr(store, "DATA", tmp_path)
    monkeypatch.setattr(store, "DEMO", True)
    from tctl import demo as d
    d.ensure()
    return tmp_path


@pytest.fixture()
def client(demo):
    from fastapi.testclient import TestClient
    from tctl import main
    importlib.reload(main)
    with TestClient(main.app) as c:
        yield c
