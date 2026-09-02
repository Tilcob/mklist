"""Tests für Phase 3 – Rohdaten-Validierung (validation_input.py).

Testfokus laut Implementierungsplan: fehlende Pflichtspalte, falscher Typ,
Leerwert trotz allow_missing_values=false, unbekannte Spalte (-> Warnung
statt Fehler), mehrere Fehler gleichzeitig (prüft lazy=True-Sammlung).

HINWEIS: pandera konnte in der Entwicklungsumgebung nicht installiert und
ausgeführt werden (keine Netzwerkverbindung in der Sandbox). Diese Tests
sind nach bestem Wissen gegen die dokumentierte pandera-API geschrieben,
aber noch nicht live verifiziert – bitte beim ersten lokalen Lauf besonders
genau auf Abweichungen achten (z. B. falls sich Spaltennamen in
SchemaErrors.failure_cases zwischen pandera-Versionen unterscheiden).
"""

import pandas as pd
import pytest

from mklist.loader import LoadedFile
from mklist.template import TemplateConfig
from mklist.validation_input import validate_input_file, validate_input_files


def _template() -> TemplateConfig:
    return TemplateConfig.model_validate(
        {
            "template_name": "Test-Vorlage",
            "version": "1.0",
            "input": {
                "required_columns": ["Artikelnummer", "Farbe", "Laufmeter"],
                "column_types": {
                    "Artikelnummer": "string",
                    "Farbe": "string",
                    "Laufmeter": "float",
                },
                "allow_missing_values": {
                    "Artikelnummer": False,
                    "Farbe": False,
                    "Laufmeter": False,
                },
            },
            "duplicate_keys": ["Artikelnummer", "Farbe"],
            "aggregate": [{"column": "Laufmeter", "method": "sum"}],
            "output": {
                "columns_order": ["Artikelnummer", "Farbe", "Laufmeter"],
                "sort_by": ["Artikelnummer"],
                "filename_suffix": "_zusammengefasst",
            },
        }
    )


def _make_loaded(df: pd.DataFrame, filename: str = "test.csv") -> LoadedFile:
    from pathlib import Path

    return LoadedFile(filename=filename, path=Path(filename), df=df)


# ---------------------------------------------------------------------------
# Gültiger Fall
# ---------------------------------------------------------------------------


def test_valid_file_has_no_errors_and_produces_typed_df():
    df = pd.DataFrame(
        {
            "Artikelnummer": ["A1", "A2"],
            "Farbe": ["rot", "blau"],
            "Laufmeter": [12.5, 7.3],
        }
    )
    result = validate_input_file(_make_loaded(df), _template())

    assert result.is_valid
    assert not result.errors
    assert not result.warnings
    assert result.df is not None
    assert result.df["Laufmeter"].tolist() == [12.5, 7.3]


# ---------------------------------------------------------------------------
# Fehlende Pflichtspalte
# ---------------------------------------------------------------------------


def test_missing_required_column_is_an_error():
    df = pd.DataFrame({"Artikelnummer": ["A1"], "Farbe": ["rot"]})  # Laufmeter fehlt
    result = validate_input_file(_make_loaded(df), _template())

    assert not result.is_valid
    assert any("Laufmeter" in e.message for e in result.errors)
    assert result.df is None


def test_missing_required_column_skips_further_type_checks():
    # Ohne Pflichtspalte werden keine (evtl. verwirrenden) Folgefehler erzeugt
    df = pd.DataFrame({"Artikelnummer": ["A1"]})
    result = validate_input_file(_make_loaded(df), _template())

    missing_column_errors = [e for e in result.errors if "fehlt" in e.message]
    assert len(missing_column_errors) == 2  # Farbe und Laufmeter fehlen


# ---------------------------------------------------------------------------
# Falscher Typ
# ---------------------------------------------------------------------------


def test_non_numeric_value_in_float_column_is_an_error():
    df = pd.DataFrame(
        {
            "Artikelnummer": ["A1"],
            "Farbe": ["rot"],
            "Laufmeter": ["nicht_numerisch"],
        }
    )
    result = validate_input_file(_make_loaded(df), _template())

    assert not result.is_valid
    assert any(e.column == "Laufmeter" for e in result.errors)


# ---------------------------------------------------------------------------
# Leerwert trotz allow_missing_values=false
# ---------------------------------------------------------------------------


def test_missing_value_where_not_allowed_is_an_error():
    df = pd.DataFrame(
        {
            "Artikelnummer": ["A1", "A2"],
            "Farbe": ["rot", None],  # Farbe: allow_missing_values=False
            "Laufmeter": [1.0, 2.0],
        }
    )
    result = validate_input_file(_make_loaded(df), _template())

    assert not result.is_valid
    assert any(e.column == "Farbe" for e in result.errors)


# ---------------------------------------------------------------------------
# Unbekannte Spalte -> Warnung, kein Fehler
# ---------------------------------------------------------------------------


def test_unknown_column_is_a_warning_not_an_error():
    df = pd.DataFrame(
        {
            "Artikelnummer": ["A1"],
            "Farbe": ["rot"],
            "Laufmeter": [1.0],
            "Kommentar": ["irrelevant"],  # nicht in required_columns
        }
    )
    result = validate_input_file(_make_loaded(df), _template())

    assert result.is_valid  # unbekannte Spalte darf NICHT zum Abbruch führen
    assert len(result.warnings) == 1
    assert result.warnings[0].column == "Kommentar"


def test_multiple_unknown_columns_produce_one_warning_each():
    df = pd.DataFrame(
        {
            "Artikelnummer": ["A1"],
            "Farbe": ["rot"],
            "Laufmeter": [1.0],
            "Kommentar": ["x"],
            "Bemerkung": ["y"],
        }
    )
    result = validate_input_file(_make_loaded(df), _template())

    assert result.is_valid
    warned_columns = {w.column for w in result.warnings}
    assert warned_columns == {"Kommentar", "Bemerkung"}


# ---------------------------------------------------------------------------
# Mehrere Fehler gleichzeitig -> lazy=True sammelt alle, statt beim ersten
# abzubrechen
# ---------------------------------------------------------------------------


def test_multiple_errors_are_all_collected_at_once():
    df = pd.DataFrame(
        {
            "Artikelnummer": ["A1", None],  # Zeile 2: Leerwert nicht erlaubt
            "Farbe": ["rot", "blau"],
            "Laufmeter": ["nicht_numerisch", 5.0],  # Zeile 1: falscher Typ
        }
    )
    result = validate_input_file(_make_loaded(df), _template())

    assert not result.is_valid
    # beide Fehler müssen im selben Durchlauf auftauchen, nicht nur der erste
    assert any(e.column == "Artikelnummer" for e in result.errors)
    assert any(e.column == "Laufmeter" for e in result.errors)
    assert len(result.errors) >= 2


# ---------------------------------------------------------------------------
# validate_input_files: mehrere Dateien, eine kaputte bricht die anderen nicht ab
# ---------------------------------------------------------------------------


def test_validate_input_files_processes_all_independently():
    good_df = pd.DataFrame(
        {"Artikelnummer": ["A1"], "Farbe": ["rot"], "Laufmeter": [1.0]}
    )
    bad_df = pd.DataFrame({"Artikelnummer": ["A2"]})  # fehlende Spalten

    results = validate_input_files(
        [
            _make_loaded(good_df, "gut.csv"),
            _make_loaded(bad_df, "schlecht.csv"),
        ],
        _template(),
    )

    assert len(results) == 2
    by_name = {r.filename: r for r in results}
    assert by_name["gut.csv"].is_valid
    assert not by_name["schlecht.csv"].is_valid
