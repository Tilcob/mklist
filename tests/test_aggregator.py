"""Tests für Phase 4 – Zusammenführen & Aggregation (aggregator.py).

Testfokus laut Implementierungsplan: Gruppierung, Aggregation, Summenbildung.
Die Kernlogik (Gruppierung, Spaltenreihenfolge/Sortierung, Summenvergleich)
wurde während der Entwicklung zusätzlich isoliert mit reinem pandas
gegengeprüft.
"""

import pandas as pd

from mklist.aggregator import aggregate, merge_and_aggregate, merge_dataframes
from mklist.template import TemplateConfig


def _template(**overrides) -> TemplateConfig:
    data = {
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
    data.update(overrides)
    return TemplateConfig.model_validate(data)


# ---------------------------------------------------------------------------
# merge_dataframes
# ---------------------------------------------------------------------------


def test_merge_dataframes_concatenates_rows():
    df1 = pd.DataFrame({"Artikelnummer": ["A1"], "Farbe": ["rot"], "Laufmeter": [1.0]})
    df2 = pd.DataFrame({"Artikelnummer": ["A2"], "Farbe": ["blau"], "Laufmeter": [2.0]})

    merged = merge_dataframes([df1, df2])

    assert len(merged) == 2
    assert set(merged["Artikelnummer"]) == {"A1", "A2"}


def test_merge_dataframes_empty_list_raises():
    import pytest

    with pytest.raises(ValueError):
        merge_dataframes([])


# ---------------------------------------------------------------------------
# aggregate – Gruppierung & Summenbildung
# ---------------------------------------------------------------------------


def test_aggregate_sums_duplicates():
    df = pd.DataFrame(
        {
            "Artikelnummer": ["A2", "A1", "A1", "A3"],
            "Farbe": ["blau", "rot", "rot", "gruen"],
            "Laufmeter": [3.0, 10.5, 5.25, 2.2],
        }
    )
    result = aggregate(df, _template())

    row_a1 = result.df[result.df["Artikelnummer"] == "A1"].iloc[0]
    assert row_a1["Laufmeter"] == 15.75
    assert len(result.df) == 3  # A1 zusammengefasst, A2 + A3 bleiben einzeln


def test_aggregate_sums_before_equals_sums_after():
    df = pd.DataFrame(
        {
            "Artikelnummer": ["A1", "A1", "A2"],
            "Farbe": ["rot", "rot", "blau"],
            "Laufmeter": [10.5, 5.25, 3.0],
        }
    )
    result = aggregate(df, _template())

    assert round(result.sums_before["Laufmeter"], 2) == round(
        result.sums_after["Laufmeter"], 2
    )
    assert round(result.sums_before["Laufmeter"], 2) == 18.75


def test_aggregate_no_duplicates_leaves_rows_unchanged():
    df = pd.DataFrame(
        {
            "Artikelnummer": ["A1", "A2", "A3"],
            "Farbe": ["rot", "blau", "gruen"],
            "Laufmeter": [1.0, 2.0, 3.0],
        }
    )
    result = aggregate(df, _template())

    assert result.input_row_count == 3
    assert result.result_row_count == 3
    assert round(result.sums_before["Laufmeter"], 2) == round(
        result.sums_after["Laufmeter"], 2
    )


# ---------------------------------------------------------------------------
# aggregate – Spaltenreihenfolge & Sortierung
# ---------------------------------------------------------------------------


def test_aggregate_respects_columns_order_and_sort_by():
    df = pd.DataFrame(
        {
            "Artikelnummer": ["A3", "A1", "A2"],
            "Farbe": ["gruen", "rot", "blau"],
            "Laufmeter": [3.0, 1.0, 2.0],
        }
    )
    result = aggregate(df, _template())

    assert list(result.df.columns) == ["Artikelnummer", "Farbe", "Laufmeter"]
    assert result.df["Artikelnummer"].tolist() == ["A1", "A2", "A3"]  # sortiert


# ---------------------------------------------------------------------------
# aggregate – Summen-Sanity nur für method=sum, nicht für mean/count
# ---------------------------------------------------------------------------


def test_aggregate_no_sum_tracking_for_count_method():
    template = _template(
        aggregate=[{"column": "Farbe", "method": "count"}],
        output={
            "columns_order": ["Artikelnummer", "Farbe"],
            "sort_by": ["Artikelnummer"],
            "filename_suffix": "_zusammengefasst",
        },
    )
    df = pd.DataFrame(
        {
            "Artikelnummer": ["A1", "A1", "A2"],
            "Farbe": ["rot", "rot", "blau"],
            "Laufmeter": [1.0, 1.0, 1.0],
        }
    )
    result = aggregate(df, template)

    # Kein sum-Rule vorhanden -> keine Summen-Tracking-Einträge
    assert result.sums_before == {}
    assert result.sums_after == {}


def test_aggregate_count_values_are_correct():
    template = _template(
        aggregate=[{"column": "Farbe", "method": "count"}],
        output={
            "columns_order": ["Artikelnummer", "Farbe"],
            "sort_by": ["Artikelnummer"],
            "filename_suffix": "_zusammengefasst",
        },
    )
    df = pd.DataFrame(
        {
            "Artikelnummer": ["A1", "A1", "A2"],
            "Farbe": ["rot", "rot", "blau"],
            "Laufmeter": [1.0, 1.0, 1.0],
        }
    )
    result = aggregate(df, template)

    row_a1 = result.df[result.df["Artikelnummer"] == "A1"].iloc[0]
    assert row_a1["Farbe"] == 2


# ---------------------------------------------------------------------------
# merge_and_aggregate – End-to-End der Phase
# ---------------------------------------------------------------------------


def test_merge_and_aggregate_end_to_end():
    df1 = pd.DataFrame({"Artikelnummer": ["A1"], "Farbe": ["rot"], "Laufmeter": [10.5]})
    df2 = pd.DataFrame({"Artikelnummer": ["A1"], "Farbe": ["rot"], "Laufmeter": [5.25]})
    df3 = pd.DataFrame({"Artikelnummer": ["A2"], "Farbe": ["blau"], "Laufmeter": [3.0]})

    result = merge_and_aggregate([df1, df2, df3], _template())

    assert result.input_row_count == 3
    assert result.result_row_count == 2
    row_a1 = result.df[result.df["Artikelnummer"] == "A1"].iloc[0]
    assert row_a1["Laufmeter"] == 15.75
    assert round(result.sums_before["Laufmeter"], 2) == round(
        result.sums_after["Laufmeter"], 2
    )
