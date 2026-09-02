"""Rohdaten-Validierung pro Eingabedatei (Ebene 2).

Baut dynamisch aus der TemplateConfig ein pandera-DataFrameSchema und prüft
jede eingelesene Datei einzeln dagegen – bevor irgendetwas zusammengeführt
wird. Siehe mklist-pandera-validierung-konzept.md, Abschnitt "Ebene 2".

Geprüft wird:
  - Spalten-Existenz (required_columns)
  - Typkonformität (column_types) – über eine eigene Coercibility-Prüfung,
    nicht über pandera's eingebaute dtype-Prüfung, da unsere Rohdaten aus
    Phase 2 bewusst noch nicht typisiert sind
  - Missing Values (allow_missing_values) – über pandera's nullable-Flag
  - Unbekannte Spalten – KEIN Fehler, sondern eine Warnung pro Spalte

Nutzt lazy=True, damit alle Fehler einer Datei in einem Durchlauf gesammelt
werden, statt bei jedem erneuten Lauf nur den nächsten einzelnen Fehler zu
zeigen.

HINWEIS: pandera konnte in der Entwicklungsumgebung nicht installiert und
live getestet werden (kein Netzwerkzugriff in der Sandbox). Die reine
Coercibility-Logik (_is_coercible) wurde isoliert mit pandas verifiziert.
Die pandera-Integration selbst (SchemaErrors.failure_cases-Spalten,
Check-Verhalten bei element_wise) sollte beim ersten lokalen Testlauf
gegengeprüft werden.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
import pandera.pandas as pa
from pandera.pandas import Check, Column
from pandera.errors import SchemaErrors

from .loader import LoadedFile
from .template import ColumnType, TemplateConfig

# Zeilennummer für Fehlermeldungen: DataFrame-Index ist 0-basiert und zählt
# ab der ersten Datenzeile; +2 ergibt die Zeilennummer, wie man sie in Excel/
# einer Textdatei sehen würde (1 = Header-Zeile, 2 = erste Datenzeile).
_ROW_NUMBER_OFFSET = 2


@dataclass
class ColumnIssue:
    """Ein einzelnes Validierungsproblem. row=None bedeutet: betrifft die
    ganze Spalte (z. B. fehlende Pflichtspalte, unbekannte Spalte), nicht
    eine einzelne Zeile."""

    column: str
    message: str
    row: int | None = None


@dataclass
class FileValidationResult:
    """Ergebnis der Ebene-2-Validierung für genau eine Datei."""

    filename: str
    errors: list[ColumnIssue] = field(default_factory=list)
    warnings: list[ColumnIssue] = field(default_factory=list)
    # Nur bei is_valid gesetzt: das geprüfte, typkonvertierte DataFrame,
    # bereit für Phase 4 (Zusammenführen & Aggregation).
    df: pd.DataFrame | None = None

    @property
    def is_valid(self) -> bool:
        return not self.errors


def _is_coercible(value: object, column_type: ColumnType) -> bool:
    """Prüft, ob sich ein einzelner Wert sauber in den Zieltyp umwandeln
    lässt. Leerwerte gelten hier immer als "konvertierbar" – ob ein Leerwert
    erlaubt ist, wird separat über allow_missing_values/nullable geprüft."""
    if pd.isna(value):
        return True

    if column_type == ColumnType.STRING:
        return True

    if column_type == ColumnType.FLOAT:
        try:
            float(value)
        except (TypeError, ValueError):
            return False
        return True

    if column_type == ColumnType.INT:
        try:
            as_float = float(value)
        except (TypeError, ValueError):
            return False
        return as_float.is_integer()

    if column_type == ColumnType.DATE:
        try:
            pd.to_datetime(value)
        except (TypeError, ValueError):
            return False
        return True

    raise ValueError(f"Unbekannter ColumnType: {column_type}")  # pragma: no cover


def _coerce_column(series: pd.Series, column_type: ColumnType) -> pd.Series:
    """Wandelt eine bereits als gültig geprüfte Spalte tatsächlich in den
    Zieltyp um (wird erst nach erfolgreicher Validierung aufgerufen)."""
    if column_type == ColumnType.STRING:
        return series.astype("string")
    if column_type in (ColumnType.INT, ColumnType.FLOAT):
        return pd.to_numeric(series, errors="coerce")
    if column_type == ColumnType.DATE:
        return pd.to_datetime(series, errors="coerce")
    raise ValueError(f"Unbekannter ColumnType: {column_type}")  # pragma: no cover


def build_input_schema(template: TemplateConfig) -> pa.DataFrameSchema:
    """Baut dynamisch ein pandera-DataFrameSchema aus der Vorlage.

    strict=False: unbekannte Spalten werden NICHT von pandera abgelehnt –
    die Warnung dafür wird separat in validate_input_file() erzeugt, nicht
    über das Schema selbst (siehe Konzept: unbekannte Spalten sind erlaubt,
    lösen aber eine Warnung aus).
    """
    columns: dict[str, Column] = {}

    for name in template.input.required_columns:
        column_type = template.input.column_types[name]
        nullable = template.input.allow_missing_values.get(name, False)

        type_check = Check(
            lambda series, ct=column_type: series.map(lambda v: _is_coercible(v, ct)),
            element_wise=False,
            name=f"coercible_to_{column_type.value}",
            error=f"Wert lässt sich nicht in Typ '{column_type.value}' umwandeln.",
        )

        columns[name] = Column(
            checks=[type_check],
            nullable=nullable,
            required=True,
            coerce=False,
        )

    return pa.DataFrameSchema(columns, strict=False)


def _find_unknown_columns(df: pd.DataFrame, template: TemplateConfig) -> list[str]:
    known = set(template.input.required_columns)
    return [col for col in df.columns if col not in known]


def _find_missing_columns(df: pd.DataFrame, template: TemplateConfig) -> list[str]:
    return [col for col in template.input.required_columns if col not in df.columns]


def _row_number_from_index(index_value: object) -> int | None:
    if index_value is None or (isinstance(index_value, float) and pd.isna(index_value)):
        return None
    try:
        return int(index_value) + _ROW_NUMBER_OFFSET
    except (TypeError, ValueError):
        return None


def _translate_schema_errors(exc: SchemaErrors) -> list[ColumnIssue]:
    """Übersetzt pandera's gesammelte SchemaErrors (lazy=True) in unsere
    eigene ColumnIssue-Liste, mit lesbarer Zeilennummer statt Roh-Index."""
    issues: list[ColumnIssue] = []

    for _, failure in exc.failure_cases.iterrows():
        column = failure.get("column")
        check_name = failure.get("check")
        failure_case = failure.get("failure_case")
        row_no = _row_number_from_index(failure.get("index"))

        if check_name == "not_nullable":
            message = "Leerwert nicht erlaubt."
        else:
            message = f"Wert '{failure_case}' ist ungültig."

        location = f"Spalte '{column}'" + (f", Zeile {row_no}" if row_no else "")
        issues.append(
            ColumnIssue(
                column=str(column), row=row_no, message=f"{location}: {message}"
            )
        )

    return issues


def validate_input_file(
    loaded: LoadedFile, template: TemplateConfig
) -> FileValidationResult:
    """Validiert eine einzelne eingelesene Datei gegen die Vorlage.

    Reihenfolge:
      1. Fehlende Pflichtspalten (harter Abbruch für diese Datei, weitere
         Prüfung ergibt ohne Pflichtspalten keinen Sinn)
      2. Unbekannte Spalten (Warnung pro Spalte, kein Abbruch)
      3. pandera-Schema (lazy=True): Typkonformität + Leerwerte
    """
    result = FileValidationResult(filename=loaded.filename)
    df = loaded.df

    missing_columns = _find_missing_columns(df, template)
    for column in missing_columns:
        result.errors.append(
            ColumnIssue(column=column, message=f"Pflichtspalte '{column}' fehlt.")
        )

    for column in _find_unknown_columns(df, template):
        result.warnings.append(
            ColumnIssue(column=column, message=f"Unbekannte Spalte '{column}'.")
        )

    if missing_columns:
        # Ohne Pflichtspalten kann das Schema gar nicht sinnvoll geprüft
        # werden – Abbruch für diese Datei, andere Dateien laufen weiter.
        return result

    schema = build_input_schema(template)

    try:
        schema.validate(df, lazy=True)
    except SchemaErrors as exc:
        result.errors.extend(_translate_schema_errors(exc))
        return result

    coerced = df.copy()
    for name in template.input.required_columns:
        column_type = template.input.column_types[name]
        coerced[name] = _coerce_column(df[name], column_type)

    result.df = coerced
    return result


def validate_input_files(
    loaded_files: list[LoadedFile], template: TemplateConfig
) -> list[FileValidationResult]:
    """Validiert eine Liste eingelesener Dateien gegen dieselbe Vorlage.
    Eine kaputte Datei bricht die Prüfung der übrigen Dateien nicht ab."""
    return [validate_input_file(loaded, template) for loaded in loaded_files]
