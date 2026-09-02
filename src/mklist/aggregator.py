"""Zusammenführen & Aggregation (Phase 4).

Nimmt die bereits einzeln validierten und typkonvertierten DataFrames aus
Phase 3 entgegen, führt sie zusammen und aggregiert Duplikate gemäß
duplicate_keys/aggregate aus der Vorlage.

Nur Dateien, die Phase 3 erfolgreich validiert hat (FileValidationResult.df
ist nicht None), dürfen hier ankommen – das Filtern selbst (inkl. der
--strict-Entscheidung, ob Dateien mit Warnungen ausgeschlossen werden)
gehört zur Orchestrierung in Phase 8, nicht in dieses Modul.

Hält für Phase 5 (Ergebnis-Validierung) die Summen vor/nach der Aggregation
fest – gemäß Konzeptentscheidung ausschließlich für aggregate-Regeln mit
method=sum, da nur dort ein exakter Vorher/Nachher-Summenvergleich
inhaltlich sinnvoll ist (bei mean/count ergibt ein solcher Vergleich keinen
Sinn und wird daher nicht gebildet).

Siehe: mklist-konzept.md (Schritt 4-5), mklist-pandera-validierung-konzept.md
(Ebene 3, Summen-Sanity-Check).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from .template import AggregateMethod, TemplateConfig

# Mapping von unserer AggregateMethod auf den von pandas' .agg() erwarteten
# Funktionsnamen. Bewusst als explizite Tabelle statt method.value direkt zu
# verwenden, damit ein künftig hinzukommender Enum-Wert nicht automatisch
# (und unbemerkt) an pandas durchgereicht wird, ohne dass dieser Mapping-
# Schritt bewusst erweitert wurde.
_PANDAS_AGG_FUNC = {
    AggregateMethod.SUM: "sum",
    AggregateMethod.MEAN: "mean",
    AggregateMethod.COUNT: "count",
}


@dataclass
class AggregationResult:
    """Ergebnis von Zusammenführen + Aggregation, bereit für Phase 5/6."""

    df: pd.DataFrame
    # Nur für aggregate-Spalten mit method=sum befüllt (siehe Moduldoku).
    sums_before: dict[str, float] = field(default_factory=dict)
    sums_after: dict[str, float] = field(default_factory=dict)
    input_row_count: int = 0
    result_row_count: int = 0


def merge_dataframes(dfs: list[pd.DataFrame]) -> pd.DataFrame:
    """Führt mehrere bereits validierte DataFrames zu einem zusammen."""
    if not dfs:
        raise ValueError("Keine DataFrames zum Zusammenführen übergeben.")
    return pd.concat(dfs, ignore_index=True)


def _sum_columns(template: TemplateConfig) -> list[str]:
    """Spalten, für die method=sum gilt – einzige Spalten, für die der
    Summen-Sanity-Check in Phase 5 sinnvoll ist."""
    return [
        rule.column for rule in template.aggregate if rule.method == AggregateMethod.SUM
    ]


def aggregate(merged_df: pd.DataFrame, template: TemplateConfig) -> AggregationResult:
    """Gruppiert merged_df nach duplicate_keys und aggregiert gemäß
    template.aggregate. Ordnet und sortiert das Ergebnis gemäß
    template.output."""
    sum_columns = _sum_columns(template)
    sums_before = {col: float(merged_df[col].sum()) for col in sum_columns}

    agg_map = {
        rule.column: _PANDAS_AGG_FUNC[rule.method] for rule in template.aggregate
    }

    grouped = merged_df.groupby(
        template.duplicate_keys, as_index=False, dropna=False
    ).agg(agg_map)

    ordered = grouped[template.output.columns_order]
    if template.output.sort_by:
        ordered = ordered.sort_values(by=template.output.sort_by)
    result_df = ordered.reset_index(drop=True)

    sums_after = {col: float(result_df[col].sum()) for col in sum_columns}

    return AggregationResult(
        df=result_df,
        sums_before=sums_before,
        sums_after=sums_after,
        input_row_count=len(merged_df),
        result_row_count=len(result_df),
    )


def merge_and_aggregate(
    dfs: list[pd.DataFrame], template: TemplateConfig
) -> AggregationResult:
    """Komfortfunktion: merge_dataframes() + aggregate() in einem Schritt."""
    merged = merge_dataframes(dfs)
    return aggregate(merged, template)
