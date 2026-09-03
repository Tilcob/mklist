"""Ausgabe schreiben (Phase 6).

Schreibt das geprüfte Ergebnis-DataFrame (nach Phase 4 + erfolgreicher
Phase-5-Validierung) als .xlsx-Datei. Kennt selbst KEINE --dry-run-Logik –
das ist eine Entscheidung der Orchestrierung in Phase 8: bei --dry-run ruft
das CLI write_result() einfach nicht auf und trägt stattdessen den über
resolve_output_path() ermittelten Pfad als "hätte geschrieben nach: ..."
in den Report ein.

Default-Ausgabepfad (siehe mklist-cli-konzept.md + mklist-konzept.md):
Kombiniert <input-dir>/ergebnis_<template_name> mit dem optionalen
output.filename_suffix aus der Vorlage, z. B.:
    ergebnis_Standard-Auswertung_zusammengefasst.xlsx
Diese Kombination ist eine sinnvolle Zusammenführung zweier im Konzept
getrennt beschriebener Regeln (CLI-Default-Pfad und filename_suffix aus der
Vorlage) und sollte bei Bedarf nochmal bestätigt werden.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from .template import TemplateConfig


class WriteError(Exception):
    """Wird geworfen, wenn die Ausgabedatei nicht geschrieben werden kann."""


def _sanitize_filename(name: str) -> str:
    """Macht einen beliebigen Vorlagen-Namen dateinamensicher: nur
    Buchstaben/Zahlen/Unterstrich/Bindestrich, keine Mehrfach-Unterstriche,
    kein führender/nachgestellter Unterstrich. Fällt auf 'vorlage' zurück,
    falls nach dem Bereinigen nichts Sinnvolles übrig bleibt (z. B. ein
    Vorlagen-Name nur aus Sonderzeichen)."""
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", name.strip())
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    return cleaned or "vorlage"


def default_output_path(input_dir: Path | str, template: TemplateConfig) -> Path:
    """Ermittelt den Default-Ausgabepfad, falls --output nicht angegeben
    wurde: <input-dir>/ergebnis_<template_name><filename_suffix>.xlsx"""
    input_dir = Path(input_dir)
    safe_name = _sanitize_filename(template.template_name)
    suffix = template.output.filename_suffix or ""
    return input_dir / f"merged_{safe_name}{suffix}.xlsx"


def resolve_output_path(
    output_arg: Path | str | None,
    input_dir: Path | str,
    template: TemplateConfig,
) -> Path:
    """Löst den tatsächlich zu verwendenden Ausgabepfad auf: explizit
    angegebener --output-Pfad hat Vorrang, sonst der Default."""
    if output_arg:
        return Path(output_arg)
    return default_output_path(input_dir, template)


def write_result(df: pd.DataFrame, output_path: Path | str) -> Path:
    """Schreibt das Ergebnis-DataFrame als .xlsx-Datei. Erstellt den
    Zielordner, falls er noch nicht existiert. Gibt den tatsächlich
    geschriebenen Pfad zurück."""
    output_path = Path(output_path)

    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        df.to_excel(output_path, index=False)
    except OSError as exc:
        raise WriteError(
            f"Ausgabedatei konnte nicht geschrieben werden: {output_path}\n{exc}"
        ) from exc

    return output_path
