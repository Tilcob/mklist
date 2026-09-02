"""Tests für Phase 2 – Datei-Einlesen (loader.py).

Testfokus laut Implementierungsplan: Excel/CSV-Einlesen, Formatfehler.
Alle Testfälle wurden während der Entwicklung gegen echte, erzeugte
Testdateien manuell verifiziert (siehe Implementierungs-Notizen).
"""

from pathlib import Path

import pandas as pd
import pytest

from mklist.loader import (
    FileLoadError,
    discover_input_files,
    load_csv,
    load_excel,
    load_file,
    load_input_files,
)


# ---------------------------------------------------------------------------
# Fixtures: Testdateien in einem temporären Ordner erzeugen
# ---------------------------------------------------------------------------


@pytest.fixture
def valid_excel_file(tmp_path: Path) -> Path:
    df = pd.DataFrame(
        {
            "Artikelnummer": ["A1", "A2"],
            "Farbe": ["rot", "blau"],
            "Laufmeter": [12.5, 7.3],
        }
    )
    path = tmp_path / "valid.xlsx"
    df.to_excel(path, index=False)
    return path


@pytest.fixture
def valid_csv_file(tmp_path: Path) -> Path:
    path = tmp_path / "valid.csv"
    path.write_text(
        "Artikelnummer;Farbe;Laufmeter\nA3;gruen;5.25\nA4;gelb;3.10\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def wrong_separator_csv_file(tmp_path: Path) -> Path:
    path = tmp_path / "wrong_sep.csv"
    path.write_text(
        "Artikelnummer,Farbe,Laufmeter\nA5,rot,1.0\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def wrong_encoding_csv_file(tmp_path: Path) -> Path:
    path = tmp_path / "wrong_encoding.csv"
    with open(path, "wb") as f:
        f.write("Artikelnummer;Farbe;Laufmeter\n".encode("utf-8"))
        f.write("A6;grün;2.0\n".encode("latin-1"))  # ungültig in utf-8
    return path


@pytest.fixture
def empty_csv_file(tmp_path: Path) -> Path:
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# discover_input_files
# ---------------------------------------------------------------------------


def test_discover_input_files_finds_mixed_types(
    tmp_path: Path, valid_excel_file: Path, valid_csv_file: Path
):
    other_file = tmp_path / "notes.txt"
    other_file.write_text("ignoriert mich", encoding="utf-8")

    found = discover_input_files(tmp_path)
    found_names = {p.name for p in found}

    assert found_names == {"valid.xlsx", "valid.csv"}
    assert "notes.txt" not in found_names


def test_discover_input_files_sorted_deterministically(
    tmp_path: Path, valid_excel_file: Path, valid_csv_file: Path
):
    found = discover_input_files(tmp_path)
    assert [p.name for p in found] == sorted(p.name for p in found)


def test_discover_input_files_missing_dir(tmp_path: Path):
    missing = tmp_path / "does_not_exist"
    with pytest.raises(FileLoadError, match="nicht gefunden"):
        discover_input_files(missing)


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------


def test_load_excel_reads_columns_and_values(valid_excel_file: Path):
    df = load_excel(valid_excel_file)
    assert list(df.columns) == ["Artikelnummer", "Farbe", "Laufmeter"]
    assert df.loc[0, "Artikelnummer"] == "A1"
    assert df.loc[0, "Laufmeter"] == 12.5


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


def test_load_csv_reads_columns_and_values(valid_csv_file: Path):
    df = load_csv(valid_csv_file)
    assert list(df.columns) == ["Artikelnummer", "Farbe", "Laufmeter"]
    assert df.loc[0, "Artikelnummer"] == "A3"
    assert df.loc[0, "Laufmeter"] == 5.25


def test_load_csv_decimal_point_not_comma(valid_csv_file: Path):
    df = load_csv(valid_csv_file)
    # Werte müssen als float mit Punkt als Dezimaltrennzeichen erkannt werden
    assert df["Laufmeter"].dtype.kind == "f"


def test_load_csv_wrong_separator_raises(wrong_separator_csv_file: Path):
    with pytest.raises(FileLoadError, match="Trennzeichen"):
        load_csv(wrong_separator_csv_file)


def test_load_csv_wrong_encoding_raises(wrong_encoding_csv_file: Path):
    with pytest.raises(FileLoadError, match="utf-8"):
        load_csv(wrong_encoding_csv_file)


def test_load_csv_empty_file_raises(empty_csv_file: Path):
    with pytest.raises(FileLoadError):
        load_csv(empty_csv_file)


# ---------------------------------------------------------------------------
# load_file (Dispatch nach Endung)
# ---------------------------------------------------------------------------


def test_load_file_dispatches_to_excel(valid_excel_file: Path):
    result = load_file(valid_excel_file)
    assert result.filename == "valid.xlsx"
    assert not result.df.empty


def test_load_file_dispatches_to_csv(valid_csv_file: Path):
    result = load_file(valid_csv_file)
    assert result.filename == "valid.csv"
    assert not result.df.empty


def test_load_file_unsupported_extension(tmp_path: Path):
    path = tmp_path / "data.txt"
    path.write_text("egal", encoding="utf-8")
    with pytest.raises(FileLoadError, match="nicht unterstützt"):
        load_file(path)


# ---------------------------------------------------------------------------
# load_input_files (ganzer Ordner, Fehler werden gesammelt statt abzubrechen)
# ---------------------------------------------------------------------------


def test_load_input_files_collects_errors_without_aborting(
    tmp_path: Path,
    valid_excel_file: Path,
    valid_csv_file: Path,
    wrong_separator_csv_file: Path,
):
    loaded, errors = load_input_files(tmp_path)

    loaded_names = {lf.filename for lf in loaded}
    assert loaded_names == {"valid.xlsx", "valid.csv"}

    assert len(errors) == 1
    assert "wrong_sep.csv" in str(errors[0])


def test_load_input_files_empty_dir_raises(tmp_path: Path):
    with pytest.raises(FileLoadError, match="Keine unterstützten Dateien"):
        load_input_files(tmp_path)


def test_load_input_files_normalizes_column_whitespace(tmp_path: Path):
    path = tmp_path / "whitespace.csv"
    path.write_text(
        " Artikelnummer ;Farbe;Laufmeter\nA1;rot;1.0\n",
        encoding="utf-8",
    )
    loaded, errors = load_input_files(tmp_path)
    assert not errors
    assert "Artikelnummer" in loaded[0].df.columns
