"""Datei-Einlesen (Excel & CSV).

Durchsucht einen Eingabeordner nach unterstützten Dateien (.xlsx, .xls, .csv,
gemischt oder einheitlich) und liest sie in DataFrames ein. Wendet dabei nur
das feste, dokumentierte Format an (siehe mklist-cli-konzept.md, Abschnitt
"CSV-Format") – keine automatische Erkennung von Trennzeichen, Encoding oder
Dezimalformat.

Diese Phase prüft NICHT, ob die eingelesenen Daten inhaltlich zur Vorlage
passen (Pflichtspalten, Typen, Leerwerte) – das übernimmt Phase 3
(validation_input.py). Hier wird nur sichergestellt, dass sich eine Datei
überhaupt lesen lässt.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

SUPPORTED_EXCEL_SUFFIXES = (".xlsx", ".xls")
SUPPORTED_CSV_SUFFIX = ".csv"
SUPPORTED_SUFFIXES = SUPPORTED_EXCEL_SUFFIXES + (SUPPORTED_CSV_SUFFIX,)

# Feste CSV-Parameter (siehe mklist-cli-konzept.md) – bewusst keine
# Auto-Erkennung, um stille Fehlinterpretationen auszuschließen.
CSV_SEPARATOR = ";"
CSV_ENCODING = "utf-8"
CSV_DECIMAL = "."


class FileLoadError(Exception):
    """Wird geworfen, wenn eine einzelne Datei nicht gelesen werden kann
    (falsches Format, kaputte Datei, falscher Trenner/Encoding etc.).
    Enthält den Dateinamen in der Fehlermeldung."""


@dataclass(frozen=True)
class LoadedFile:
    """Eine erfolgreich eingelesene, aber noch UNGEPRÜFTE Eingabedatei."""

    filename: str
    path: Path
    df: pd.DataFrame


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Normalisiert Spaltennamen (Unicode-Form, Whitespace) – analog zur
    bestehenden GUI-App, damit z. B. unterschiedlich kodierte Umlaute oder
    führende/nachgestellte Leerzeichen nicht zu falsch-negativen
    Spalten-Treffern führen."""
    df = df.copy()
    df.columns = [unicodedata.normalize("NFC", str(col)).strip() for col in df.columns]
    return df


def discover_input_files(input_dir: Path | str) -> list[Path]:
    """Findet alle unterstützten Dateien (.xlsx, .xls, .csv) in einem Ordner,
    gemischt oder einheitlich. Nicht rekursiv – nur die Dateien direkt im
    angegebenen Ordner. Ergebnis ist nach Dateiname sortiert, damit die
    Verarbeitungsreihenfolge deterministisch und reproduzierbar ist."""
    input_dir = Path(input_dir)

    if not input_dir.exists():
        raise FileLoadError(f"Eingabeordner nicht gefunden: {input_dir}")
    if not input_dir.is_dir():
        raise FileLoadError(f"Eingabepfad ist kein Ordner: {input_dir}")

    files = [
        p
        for p in input_dir.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES
    ]
    return sorted(files, key=lambda p: p.name)


def load_excel(path: Path) -> pd.DataFrame:
    """Liest eine .xlsx/.xls-Datei ein. Nutzt decimal="," wie die bestehende
    GUI-App (deutsche Excel-Exporte verwenden i. d. R. Komma als
    Dezimaltrennzeichen)."""
    try:
        df = pd.read_excel(path, decimal=",")
    except Exception as exc:  # noqa: BLE001 - bewusst breit, wird umformuliert
        raise FileLoadError(
            f"Datei '{path.name}' konnte nicht als Excel-Datei gelesen werden: {exc}"
        ) from exc
    return _normalize_columns(df)


def load_csv(path: Path) -> pd.DataFrame:
    """Liest eine .csv-Datei mit fest vorgegebenem Format ein: ';'-Trennzeichen,
    utf-8-Encoding, '.' als Dezimaltrennzeichen, Header-Zeile Pflicht. Keine
    automatische Erkennung – bei Abweichung vom erwarteten Format wird ein
    klarer Fehler mit Dateinamen geworfen, statt still zu raten."""
    try:
        df = pd.read_csv(
            path,
            sep=CSV_SEPARATOR,
            encoding=CSV_ENCODING,
            decimal=CSV_DECIMAL,
            header=0,
        )
    except UnicodeDecodeError as exc:
        raise FileLoadError(
            f"Datei '{path.name}' ist nicht als {CSV_ENCODING} lesbar. "
            f"Erwartet wird {CSV_ENCODING}-Encoding."
        ) from exc
    except Exception as exc:  # noqa: BLE001 - bewusst breit, wird umformuliert
        raise FileLoadError(
            f"Datei '{path.name}' konnte nicht als CSV gelesen werden "
            f"(erwartetes Format: Trennzeichen '{CSV_SEPARATOR}', "
            f"Encoding {CSV_ENCODING}, Dezimaltrennzeichen '{CSV_DECIMAL}'): {exc}"
        ) from exc

    if df.shape[1] <= 1:
        # Wahrscheinlichstes Symptom eines falschen Trennzeichens: pandas
        # hat die ganze Zeile als eine einzige Spalte interpretiert.
        raise FileLoadError(
            f"Datei '{path.name}' konnte nur mit einer Spalte gelesen werden. "
            f"Vermutlich stimmt das Trennzeichen nicht mit dem erwarteten "
            f"'{CSV_SEPARATOR}' überein."
        )

    return _normalize_columns(df)


def load_file(path: Path) -> LoadedFile:
    """Liest eine einzelne Datei anhand ihrer Endung ein (.xlsx/.xls -> Excel,
    .csv -> CSV) und gibt sie als LoadedFile zurück. Wirft FileLoadError bei
    nicht unterstütztem Dateityp oder Leseproblemen."""
    suffix = path.suffix.lower()

    if suffix in SUPPORTED_EXCEL_SUFFIXES:
        df = load_excel(path)
    elif suffix == SUPPORTED_CSV_SUFFIX:
        df = load_csv(path)
    else:
        raise FileLoadError(
            f"Dateityp '{suffix}' wird nicht unterstützt: {path.name} "
            f"(unterstützt: {', '.join(SUPPORTED_SUFFIXES)})"
        )

    return LoadedFile(filename=path.name, path=path, df=df)


def load_input_files(
    input_dir: Path | str,
) -> tuple[list[LoadedFile], list[FileLoadError]]:
    """Findet und liest alle unterstützten Dateien in einem Ordner ein.

    Bricht NICHT beim ersten Lesefehler ab, sondern versucht alle gefundenen
    Dateien einzulesen und sammelt Fehler, damit der Aufrufer (Phase 3/8)
    entscheiden kann, wie mit einzelnen kaputten Dateien umgegangen wird
    (z. B. im Report vermerken statt den ganzen Lauf abzubrechen).

    Gibt ein Tupel zurück: (erfolgreich eingelesene Dateien, Fehler pro Datei).
    """
    paths = discover_input_files(input_dir)

    if not paths:
        raise FileLoadError(
            f"Keine unterstützten Dateien ({', '.join(SUPPORTED_SUFFIXES)}) "
            f"gefunden in: {input_dir}"
        )

    loaded: list[LoadedFile] = []
    errors: list[FileLoadError] = []

    for path in paths:
        try:
            loaded.append(load_file(path))
        except FileLoadError as exc:
            errors.append(exc)

    return loaded, errors
