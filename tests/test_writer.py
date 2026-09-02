"""Tests für Phase 6 – Ausgabe schreiben (writer.py).

Testfokus laut Implementierungsplan: Datei wird geschrieben / bei
--dry-run nicht (Letzteres ist Orchestrierungslogik in Phase 8 und wird
dort getestet – writer.py selbst kennt kein --dry-run, siehe Moduldoku).
Datei-schreiben- und Default-Pfad-Logik wurden zusätzlich isoliert mit
reinem pandas gegengeprüft.
"""

from pathlib import Path

import pandas as pd
import pytest

from mklist.template import TemplateConfig
from mklist.writer import default_output_path, resolve_output_path, write_result


def _template(**overrides) -> TemplateConfig:
    data = {
        "template_name": "Standard-Auswertung",
        "version": "1.0",
        "input": {
            "required_columns": ["Artikelnummer", "Laufmeter"],
            "column_types": {"Artikelnummer": "string", "Laufmeter": "float"},
            "allow_missing_values": {"Artikelnummer": False, "Laufmeter": False},
        },
        "duplicate_keys": ["Artikelnummer"],
        "aggregate": [{"column": "Laufmeter", "method": "sum"}],
        "output": {
            "columns_order": ["Artikelnummer", "Laufmeter"],
            "sort_by": ["Artikelnummer"],
            "filename_suffix": "_zusammengefasst",
        },
    }
    data.update(overrides)
    return TemplateConfig.model_validate(data)


# ---------------------------------------------------------------------------
# write_result
# ---------------------------------------------------------------------------


def test_write_result_creates_readable_xlsx(tmp_path: Path):
    df = pd.DataFrame({"Artikelnummer": ["A1", "A2"], "Laufmeter": [10.5, 3.0]})
    output_path = tmp_path / "ergebnis.xlsx"

    result_path = write_result(df, output_path)

    assert result_path == output_path
    assert output_path.exists()

    reread = pd.read_excel(output_path)
    assert reread["Artikelnummer"].tolist() == ["A1", "A2"]
    assert reread["Laufmeter"].tolist() == [10.5, 3.0]


def test_write_result_creates_missing_parent_dirs(tmp_path: Path):
    df = pd.DataFrame({"Artikelnummer": ["A1"], "Laufmeter": [1.0]})
    output_path = tmp_path / "unterordner" / "noch_ein_ordner" / "ergebnis.xlsx"

    result_path = write_result(df, output_path)

    assert result_path.exists()


# ---------------------------------------------------------------------------
# default_output_path
# ---------------------------------------------------------------------------


def test_default_output_path_combines_name_and_suffix(tmp_path: Path):
    path = default_output_path(tmp_path, _template())

    assert path.parent == tmp_path
    assert path.name == "ergebnis_Standard-Auswertung_zusammengefasst.xlsx"


def test_default_output_path_sanitizes_special_characters(tmp_path: Path):
    template = _template(template_name="Test Vorlage äöü")
    path = default_output_path(tmp_path, template)

    assert path.name == "ergebnis_Test_Vorlage_zusammengefasst.xlsx"


def test_default_output_path_without_filename_suffix(tmp_path: Path):
    template = _template(
        output={
            "columns_order": ["Artikelnummer", "Laufmeter"],
            "sort_by": ["Artikelnummer"],
            "filename_suffix": "",
        }
    )
    path = default_output_path(tmp_path, template)

    assert path.name == "ergebnis_Standard-Auswertung.xlsx"


# ---------------------------------------------------------------------------
# resolve_output_path
# ---------------------------------------------------------------------------


def test_resolve_output_path_prefers_explicit_argument(tmp_path: Path):
    explicit = tmp_path / "custom.xlsx"
    resolved = resolve_output_path(explicit, tmp_path, _template())

    assert resolved == explicit


def test_resolve_output_path_falls_back_to_default(tmp_path: Path):
    resolved = resolve_output_path(None, tmp_path, _template())

    assert resolved == default_output_path(tmp_path, _template())
