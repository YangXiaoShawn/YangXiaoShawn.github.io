import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app

from app import PROJECTS, explore


def test_project_registry():
    assert set(PROJECTS) == {
        "CasualLab",
        "Macroeconomics",
        "RealEstate",
        "TariffIncidence",
        "Microstructure",
    }


def test_explorer_has_fallback(monkeypatch):
    monkeypatch.setattr("app._dataset_rows", lambda project: (app.FALLBACK_ROWS.copy(), "test"))
    summary, rows, chart, methodology = explore("CasualLab", "fixtures")
    assert "CasualLab" in summary
    assert not rows.empty
    assert len(chart) == 4
    assert "evidence boundary" in methodology.lower()


def test_tariff_project_uses_canonical_slug(monkeypatch):
    monkeypatch.setattr("app._dataset_rows", lambda project: (app.FALLBACK_ROWS.copy(), "test"))
    summary, _, _, _ = explore("TariffIncidence", "")
    assert "/projects/tariff-incidence/" in summary
    assert "open-economic-quant-tariff-incidence" in summary


def test_microstructure_project_uses_canonical_links(monkeypatch):
    monkeypatch.setattr("app._dataset_rows", lambda project: (app.FALLBACK_ROWS.copy(), "test"))
    summary, _, _, _ = explore("Microstructure", "")
    assert "/projects/microstructure/" in summary
    assert "open-economic-quant-microstructure" in summary
