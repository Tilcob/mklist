"""Vorlagen-Modell und -Validierung (Ebene 1).

Lädt eine mklist-Vorlage (JSON) und prüft sie strukturell (Pydantic-Feldtypen)
sowie inhaltlich (Cross-Field-Regeln, z. B. referenzieren duplicate_keys
tatsächlich vorhandene Pflichtspalten). Eine erfolgreich geladene
TemplateConfig ist danach garantiert intern konsistent – alle nachfolgenden
Phasen können sich darauf verlassen, ohne diese Regeln erneut zu prüfen.

Siehe: mklist-pydantic-model-konzept.md
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ColumnType(str, Enum):
    """Erwarteter Datentyp einer Spalte."""

    STRING = "string"
    INT = "int"
    FLOAT = "float"
    DATE = "date"

    @property
    def is_numeric(self) -> bool:
        return self in (ColumnType.INT, ColumnType.FLOAT)


class AggregateMethod(str, Enum):
    """Methode, mit der Duplikat-Werte zusammengefasst werden."""

    SUM = "sum"
    MEAN = "mean"
    COUNT = "count"


# ---------------------------------------------------------------------------
# Basis-Konfiguration: unbekannte Felder sind ein Fehler, kein stilles Ignorieren
# ---------------------------------------------------------------------------


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# ---------------------------------------------------------------------------
# Sub-Models
# ---------------------------------------------------------------------------


class InputConfig(_StrictModel):
    """Beschreibt, welche Spalten eine Eingabedatei enthalten muss."""

    required_columns: list[str] = Field(min_length=1)
    column_types: dict[str, ColumnType]
    allow_missing_values: dict[str, bool]


class AggregateRule(_StrictModel):
    """Eine Aggregationsregel für eine Spalte (z. B. Laufmeter summieren)."""

    column: str
    method: AggregateMethod


class OutputConfig(_StrictModel):
    """Steuert Spaltenreihenfolge, Sortierung und Dateibenennung der Ausgabe."""

    columns_order: list[str] = Field(min_length=1)
    sort_by: list[str] = Field(default_factory=list)
    filename_suffix: str = ""


class ValueRange(_StrictModel):
    """Optionale Plausibilitätsgrenze für eine numerische Spalte im Ergebnis."""

    min: float | None = None
    max: float | None = None


# ---------------------------------------------------------------------------
# Top-Level-Model
# ---------------------------------------------------------------------------


class TemplateConfig(_StrictModel):
    """Vollständige, geprüfte mklist-Vorlage.

    Nach erfolgreichem Laden gelten alle Cross-Field-Regeln aus
    mklist-pydantic-model-konzept.md als erfüllt.
    """

    template_name: str
    version: str  # rein informativ, keine Migrationslogik

    input: InputConfig
    duplicate_keys: list[str] = Field(min_length=1)
    aggregate: list[AggregateRule] = Field(min_length=1)
    output: OutputConfig
    validation_rules: dict[str, ValueRange] = Field(default_factory=dict)

    # -- Cross-Field-Validierung (Regeln 1-5) --------------------------------

    @model_validator(mode="after")
    def _check_cross_field_rules(self) -> "TemplateConfig":
        errors: list[str] = []
        required = set(self.input.required_columns)
        numeric_columns = {
            name
            for name, col_type in self.input.column_types.items()
            if col_type.is_numeric
        }

        # Regel 1: duplicate_keys müssen in required_columns vorkommen
        for key in self.duplicate_keys:
            if key not in required:
                errors.append(
                    f"duplicate_keys: Spalte '{key}' ist nicht in "
                    f"input.required_columns enthalten."
                )

        # Regel 2: column_types-Keys müssen in required_columns vorkommen
        for column in self.input.column_types:
            if column not in required:
                errors.append(
                    f"input.column_types: Spalte '{column}' ist nicht in "
                    f"input.required_columns enthalten."
                )

        # Regel 3: aggregate[].column muss in required_columns vorkommen und
        # bei sum/mean numerisch sein
        result_columns = set(self.duplicate_keys)
        for rule in self.aggregate:
            if rule.column not in required:
                errors.append(
                    f"aggregate: Spalte '{rule.column}' ist nicht in "
                    f"input.required_columns enthalten."
                )
            elif rule.method in (AggregateMethod.SUM, AggregateMethod.MEAN):
                if rule.column not in numeric_columns:
                    errors.append(
                        f"aggregate: Methode '{rule.method.value}' auf Spalte "
                        f"'{rule.column}' erfordert einen numerischen Typ "
                        f"(int/float) in input.column_types."
                    )
            result_columns.add(rule.column)

        # Regel 4: output.sort_by / columns_order müssen im Ergebnis existieren
        # (duplicate_keys oder aggregate-Spalten)
        for field_name, columns in (
            ("output.columns_order", self.output.columns_order),
            ("output.sort_by", self.output.sort_by),
        ):
            for column in columns:
                if column not in result_columns:
                    errors.append(
                        f"{field_name}: Spalte '{column}' ist weder in "
                        f"duplicate_keys noch eine aggregate-Spalte und "
                        f"existiert daher nicht im Ergebnis."
                    )

        # Regel 5: validation_rules-Keys müssen (a) numerisch sein UND
        # (b) tatsächlich im Ergebnis existieren (duplicate_keys oder eine
        # aggregate-Spalte) – sonst gäbe es in Ebene 3 (Ergebnis-Validierung)
        # gar keine Spalte, auf die sich min/max beziehen könnten. Diese
        # zweite Teilprüfung schließt eine ursprünglich offen gelassene
        # Lücke im Konzept (siehe mklist-pydantic-model-konzept.md).
        for column in self.validation_rules:
            if column not in numeric_columns:
                errors.append(
                    f"validation_rules: Spalte '{column}' ist laut "
                    f"input.column_types nicht numerisch (int/float) – "
                    f"min/max sind hier nicht sinnvoll."
                )
            elif column not in result_columns:
                errors.append(
                    f"validation_rules: Spalte '{column}' ist weder in "
                    f"duplicate_keys noch eine aggregate-Spalte und "
                    f"existiert daher nicht im Ergebnis, auf das sich "
                    f"validation_rules bezieht."
                )

        if errors:
            raise ValueError(
                "Vorlage ist inhaltlich ungültig:\n"
                + "\n".join(f"  - {e}" for e in errors)
            )

        return self


# ---------------------------------------------------------------------------
# Laden
# ---------------------------------------------------------------------------


class TemplateLoadError(Exception):
    """Wird geworfen, wenn eine Vorlagendatei nicht gelesen oder nicht
    gegen TemplateConfig validiert werden kann. Enthält eine für Nicht-
    Entwickler verständliche Fehlermeldung mit Feldpfad und Klartext."""


def load_template(path: Path | str) -> TemplateConfig:
    """Lädt und validiert eine mklist-Vorlage aus einer JSON-Datei.

    Wirft TemplateLoadError mit einer verständlichen, zusammengefassten
    Fehlermeldung, falls die Datei nicht existiert, kein gültiges JSON
    enthält, oder die Vorlage strukturell/inhaltlich ungültig ist.
    """
    path = Path(path)

    if not path.exists():
        raise TemplateLoadError(f"Vorlagendatei nicht gefunden: {path}")

    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise TemplateLoadError(
            f"Vorlagendatei konnte nicht gelesen werden: {path}\n{exc}"
        ) from exc

    try:
        raw_data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise TemplateLoadError(
            f"Vorlagendatei ist kein gültiges JSON: {path}\n"
            f"Zeile {exc.lineno}, Spalte {exc.colno}: {exc.msg}"
        ) from exc

    try:
        return TemplateConfig.model_validate(raw_data)
    except ValidationError as exc:
        raise TemplateLoadError(_format_validation_error(path, exc)) from exc


def _format_validation_error(path: Path, exc: ValidationError) -> str:
    """Formatiert pydantic-ValidationErrors als Klartext mit Feldpfad,
    verständlich auch für Vorlagen-Pflegende ohne Python-Kenntnisse."""
    lines = [f"Vorlage ungültig: {path}"]
    for error in exc.errors():
        field_path = ".".join(str(part) for part in error["loc"]) or "(Vorlage)"
        message = error["msg"]
        lines.append(f"  - {field_path}: {message}")
    return "\n".join(lines)
