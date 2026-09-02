"""Tests für Phase 5 – Ergebnis-Validierung (validation_result.py).

Testfokus laut Implementierungsplan: absichtlich manipuliertes Aggregat
(gefälschte Summenabweichung), um sicherzustellen, dass der Summen-Check
zuverlässig greift. Zusätzlich: Duplikat-Check und validation_rules.

Duplikat-Check- und Summen-Check-Logik wurden zusätzlich isoliert mit
reinem pandas/Python gegengeprüft (siehe Implementierungs-Notizen).
"""

import pandas as pd

from mklist.aggregator import AggregationResult
from mklist.template import TemplateConfig
from mklist.validation_result import (
    check_no_remaining_duplicates,
    check_sum_consistency,
    validate_result,
)


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
# check_no_remaining_duplicates
# ---------------------------------------------------------------------------


def test_no_duplicates_after_correct_aggregation():
    df = pd.DataFrame({"Artikelnummer": ["A1", "A2"], "Farbe": ["rot", "blau"]})
    issues = check_no_remaining_duplicates(df, _template())
    assert issues == []


def test_remaining_duplicates_are_detected():
    # Absichtlich kaputtes "Ergebnis": A1/rot kommt zweimal vor, obwohl das
    # nach einer korrekten Aggregation nicht mehr passieren dürfte.
    df = pd.DataFrame(
        {
            "Artikelnummer": ["A1", "A1", "A2"],
            "Farbe": ["rot", "rot", "blau"],
            "Laufmeter": [5.0, 5.0, 3.0],
        }
    )
    issues = check_no_remaining_duplicates(df, _template())

    assert len(issues) == 1
    assert "A1" in issues[0].message


# ---------------------------------------------------------------------------
# check_sum_consistency – inkl. gefälschter Abweichung
# ---------------------------------------------------------------------------


def test_sum_consistency_passes_when_sums_match():
    agg_result = AggregationResult(
        df=pd.DataFrame(),
        sums_before={"Laufmeter": 27.95},
        sums_after={"Laufmeter": 27.95},
    )
    assert check_sum_consistency(agg_result) == []


def test_sum_consistency_tolerates_float_rounding_artifacts():
    # Reine Fliesskomma-Ungenauigkeit, keine echte Differenz -> kein Fehler
    agg_result = AggregationResult(
        df=pd.DataFrame(),
        sums_before={"Laufmeter": 27.950000000000003},
        sums_after={"Laufmeter": 27.95},
    )
    assert check_sum_consistency(agg_result) == []


def test_sum_consistency_detects_faked_deviation():
    # Absichtlich manipuliertes Aggregat: sums_after weicht deutlich ab
    agg_result = AggregationResult(
        df=pd.DataFrame(),
        sums_before={"Laufmeter": 27.95},
        sums_after={"Laufmeter": 25.00},
    )
    issues = check_sum_consistency(agg_result)

    assert len(issues) == 1
    assert "Laufmeter" in issues[0].message
    assert "27.95" in issues[0].message
    assert "25.0" in issues[0].message


def test_sum_consistency_ignores_columns_without_before_after_pair():
    # sums_after enthaelt eine Spalte, fuer die es keine sums_before gibt
    # (sollte nicht vorkommen, aber defensiv nicht crashen)
    agg_result = AggregationResult(
        df=pd.DataFrame(), sums_before={}, sums_after={"Laufmeter": 10.0}
    )
    assert check_sum_consistency(agg_result) == []


# ---------------------------------------------------------------------------
# validate_result – End-to-End
# ---------------------------------------------------------------------------


def test_validate_result_valid_case_has_no_errors():
    df = pd.DataFrame(
        {
            "Artikelnummer": ["A1", "A2"],
            "Farbe": ["rot", "blau"],
            "Laufmeter": [15.75, 3.0],
        }
    )
    agg_result = AggregationResult(
        df=df,
        sums_before={"Laufmeter": 18.75},
        sums_after={"Laufmeter": 18.75},
    )
    result = validate_result(agg_result, _template())

    assert result.is_valid


def test_validate_result_combines_duplicate_and_sum_errors():
    # Sowohl Duplikate als auch eine Summenabweichung gleichzeitig
    df = pd.DataFrame(
        {
            "Artikelnummer": ["A1", "A1"],
            "Farbe": ["rot", "rot"],
            "Laufmeter": [5.0, 5.0],
        }
    )
    agg_result = AggregationResult(
        df=df,
        sums_before={"Laufmeter": 20.0},
        sums_after={"Laufmeter": 10.0},
    )
    result = validate_result(agg_result, _template())

    assert not result.is_valid
    assert len(result.errors) >= 2


def test_validate_result_with_validation_rules_min_violation():
    template = _template(validation_rules={"Laufmeter": {"min": 0}})
    df = pd.DataFrame(
        {
            "Artikelnummer": ["A1"],
            "Farbe": ["rot"],
            "Laufmeter": [-5.0],  # verletzt min=0
        }
    )
    agg_result = AggregationResult(
        df=df,
        sums_before={"Laufmeter": -5.0},
        sums_after={"Laufmeter": -5.0},
    )
    result = validate_result(agg_result, template)

    assert not result.is_valid
    assert any("Laufmeter" in e.message for e in result.errors)


def test_validate_result_with_validation_rules_within_bounds():
    template = _template(validation_rules={"Laufmeter": {"min": 0, "max": 100}})
    df = pd.DataFrame(
        {
            "Artikelnummer": ["A1"],
            "Farbe": ["rot"],
            "Laufmeter": [50.0],
        }
    )
    agg_result = AggregationResult(
        df=df,
        sums_before={"Laufmeter": 50.0},
        sums_after={"Laufmeter": 50.0},
    )
    result = validate_result(agg_result, template)

    assert result.is_valid
