import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app

from app import PROJECTS, explore


def test_project_registry():
    assert set(PROJECTS) == {"CasualLab", "Macroeconomics"}


def test_explorer_has_fallback(monkeypatch):
    monkeypatch.setattr("app._dataset_rows", lambda project: (app.FALLBACK_ROWS.copy(), "test"))
    summary, rows, chart, methodology = explore("CasualLab", "fixtures")
    assert "CasualLab" in summary
    assert not rows.empty
    assert len(chart) == 4
    assert "evidence boundary" in methodology.lower()
