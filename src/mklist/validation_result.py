"""Ergebnis-Validierung nach der Aggregation (Ebene 3).

Prüft das von Phase 4 (aggregator.py) erzeugte Ergebnis-DataFrame, bevor es
in Phase 6 als Ausgabedatei geschrieben wird. Siehe
mklist-pandera-validierung-konzept.md, Abschnitt "Ebene 3".

Geprüft wird:
  1. validation_rules aus der Vorlage (min/max) – dynamisch aus der Vorlage
     gebautes pandera-Schema, analog zu Ebene 2
  2. Duplikat-Check: nach der Gruppierung dürfen keine doppelten
     duplicate_keys-Kombinationen mehr existieren -> harter Fehler
  3. Summen-Sanity-Check: Summe vorher/nachher (aus AggregationResult) muss
     auf 2 Nachkommastellen exakt übereinstimmen -> harter Fehler.
     Gilt gemäß Konzeptentscheidung NUR für aggregate-Spalten mit
     method=sum (siehe aggregator.py, sums_before/sums_after).

ANMERKUNG zu validation_rules ohne Bezug zum Ergebnis: Pydantic prüft beim
Laden der Vorlage nur, dass ein validation_rules-Key numerisch ist (Regel 5
im Pydantic-Konzept), nicht aber, dass diese Spalte auch tatsächlich Teil
des Ergebnisses ist (duplicate_keys oder aggregate-Spalte). Referenziert
validation_rules eine Spalte, die im Ergebnis nicht vorkommt (z. B. eine
required_column, die weder duplicate_key noch aggregiert wird, oder eine
count-Spalte, die keinen numerischen Ursprungstyp mehr hat), wird diese
Regel hier stillschweigend übersprungen, statt das Schema zum Absturz zu
bringen. Das ist eine Lücke im ursprünglichen Konzept, die hier pragmatisch
behandelt wird – bei Bedarf könnte Pydantic-Regel 5 künftig um eine
Prüfung "validation_rules-Key muss im Ergebnis existieren" erweitert werden.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd
import pandera.pandas as pa
from pandera.pandas import Check, Column
from pandera.errors import SchemaErrors

from .aggregator import AggregationResult
from .template import AggregateMethod, ColumnType, TemplateConfig

_SUM_ROUNDING_DECIMALS = 2
_ROW_NUMBER_OFFSET = 2


@dataclass
class ResultIssue:
    message: str


@dataclass
class ResultValidationResult:
    errors: list[ResultIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.errors


def _result_column_types(template: TemplateConfig) -> dict[str, ColumnType | None]:
    """Bestimmt den effektiven Typ jeder Spalte im Ergebnis-DataFrame.

    duplicate_keys behalten ihren ursprünglichen Typ aus input.column_types.
    aggregate-Spalten behalten ihren Typ bei sum/mean; bei count wird die
    Spalte zu einer reinen Zählgröße und hat keinen sinnvollen ColumnType
    aus der Vorlage mehr (-> None, wird beim Schema-Bau übersprungen).
    """
    types: dict[str, ColumnType | None] = {}
    for key in template.duplicate_keys:
        types[key] = template.input.column_types.get(key)
    for rule in template.aggregate:
        if rule.method == AggregateMethod.COUNT:
            types[rule.column] = None
        else:
            types[rule.column] = template.input.column_types.get(rule.column)
    return types


def build_result_schema(template: TemplateConfig) -> pa.DataFrameSchema:
    """Baut ein pandera-Schema für das Ergebnis-DataFrame aus
    template.validation_rules. Nur Spalten, die numerisch UND tatsächlich
    im Ergebnis vorhanden sind, werden geprüft (siehe Moduldoku oben)."""
    result_types = _result_column_types(template)
    columns: dict[str, Column] = {}

    for column_name, value_range in template.validation_rules.items():
        column_type = result_types.get(column_name)
        if column_type is None or not column_type.is_numeric:
            continue

        checks = []
        if value_range.min is not None:
            checks.append(Check.ge(value_range.min))
        if value_range.max is not None:
            checks.append(Check.le(value_range.max))

        if checks:
            columns[column_name] = Column(checks=checks, nullable=True, required=False)

    return pa.DataFrameSchema(columns, strict=False)


def _row_number_from_index(index_value: object) -> int | None:
    if index_value is None or (isinstance(index_value, float) and pd.isna(index_value)):
        return None
    try:
        return int(index_value) + _ROW_NUMBER_OFFSET
    except (TypeError, ValueError):
        return None


def _translate_result_schema_errors(exc: SchemaErrors) -> list[ResultIssue]:
    issues: list[ResultIssue] = []
    for _, failure in exc.failure_cases.iterrows():
        column = failure.get("column")
        failure_case = failure.get("failure_case")
        row_no = _row_number_from_index(failure.get("index"))
        location = f"Spalte '{column}'" + (f", Zeile {row_no}" if row_no else "")
        issues.append(
            ResultIssue(
                message=f"{location}: Wert '{failure_case}' verletzt die Plausibilitätsgrenze."
            )
        )
    return issues


def check_no_remaining_duplicates(
    df: pd.DataFrame, template: TemplateConfig
) -> list[ResultIssue]:
    """Nach der Aggregation dürfen keine doppelten duplicate_keys-
    Kombinationen mehr existieren – sonst ist die Aggregationslogik
    grundsätzlich fehlerhaft. Harter Fehler, keine Warnung."""
    duplicated_mask = df.duplicated(subset=template.duplicate_keys, keep=False)
    if not duplicated_mask.any():
        return []

    duplicated_rows = df.loc[duplicated_mask, template.duplicate_keys]
    combos = duplicated_rows.drop_duplicates()

    return [
        ResultIssue(
            message=(
                "Nach der Aggregation existieren noch doppelte "
                "duplicate_keys-Kombinationen: "
                + ", ".join(f"{col}={row[col]!r}" for col in template.duplicate_keys)
            )
        )
        for _, row in combos.iterrows()
    ]


def check_sum_consistency(aggregation_result: AggregationResult) -> list[ResultIssue]:
    """Summe vor und nach der Aggregation muss (auf 2 Nachkommastellen
    gerundet) exakt übereinstimmen. Gilt nur für aggregate-Spalten mit
    method=sum (siehe Konzeptentscheidung, aggregator.py)."""
    issues: list[ResultIssue] = []

    for column, before in aggregation_result.sums_before.items():
        after = aggregation_result.sums_after.get(column)
        if after is None:
            continue

        before_rounded = round(before, _SUM_ROUNDING_DECIMALS)
        after_rounded = round(after, _SUM_ROUNDING_DECIMALS)

        if before_rounded != after_rounded:
            issues.append(
                ResultIssue(
                    message=(
                        f"Summen-Check fehlgeschlagen für Spalte '{column}': "
                        f"Summe vorher = {before_rounded}, "
                        f"Summe nachher = {after_rounded}. Beim Zusammenführen "
                        "sind vermutlich Daten verloren gegangen oder es liegt "
                        "ein Fehler in der Aggregationslogik vor."
                    )
                )
            )

    return issues


def validate_result(
    aggregation_result: AggregationResult, template: TemplateConfig
) -> ResultValidationResult:
    """Führt alle drei Ebene-3-Prüfungen aus und sammelt deren Fehler."""
    result = ResultValidationResult()

    result.errors.extend(check_no_remaining_duplicates(aggregation_result.df, template))
    result.errors.extend(check_sum_consistency(aggregation_result))

    schema = build_result_schema(template)
    try:
        schema.validate(aggregation_result.df, lazy=True)
    except SchemaErrors as exc:
        result.errors.extend(_translate_result_schema_errors(exc))

    return result
