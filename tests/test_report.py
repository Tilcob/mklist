"""Tests für Phase 7 – Report-Erzeugung (report.py).

Testfokus laut Implementierungsplan: beide Report-Formate, alle drei
Ausgänge (Erfolg / Warnung / Fehler).

report.py wurde vor Fertigstellung dieser Tests bereits end-to-end mit
Stub-Modulen für die pydantic/pandera-abhängigen Imports real ausgeführt
(build_report, beide Renderer, write_report) – siehe Implementierungs-
Notizen. Diese Tests laufen gegen die echte Vorlagen-/Validierungs-
Infrastruktur, sobald pydantic/pandera lokal installiert sind.
"""

from datetime import datetime

import pandas as pd
import pytest

from mklist.aggregator import AggregationResult
from mklist.loader import FileLoadError
from mklist.report import (
    add_result_validation_errors,
    build_report,
    render_html,
    render_markdown,
    write_report,
)
from mklist.template import TemplateConfig
from mklist.validation_input import ColumnIssue, FileValidationResult
from mklist.validation_result import ResultIssue, ResultValidationResult


def _template() -> TemplateConfig:
    return TemplateConfig.model_validate(
        {
            "template_name": "Standard-Auswertung",
            "version": "1.0",
            "input": {
                "required_columns": ["Artikelnummer", "Laufmeter"],
                "column_types": {"Artikelnummer": "string", "Laufmeter": "float"},
                "allow_missing_values": {"Artikelnummer": False, "Laufmeter": False},
            },
            "duplicate_keys": ["Artikelnummer"],
            "aggregate": [{"column": "Laufmeter", "method": "sum"}],
            "output": {
                "columns_order": ["Artikelnummer", "Laufmeter"],
                "sort_by": ["Artikelnummer"],
                "filename_suffix": "_zusammengefasst",
            },
        }
    )


_TIMESTAMP = datetime(2026, 9, 2, 10, 0, 0)


# ---------------------------------------------------------------------------
# Fall: Erfolg
# ---------------------------------------------------------------------------


def test_success_case_status_and_rendering():
    fvr = FileValidationResult(
        filename="gut.csv",
        df=pd.DataFrame({"Artikelnummer": ["A1"], "Laufmeter": [10.5]}),
    )
    agg = AggregationResult(
        df=pd.DataFrame({"Artikelnummer": ["A1"], "Laufmeter": [10.5]}),
        sums_before={"Laufmeter": 10.5},
        sums_after={"Laufmeter": 10.5},
        input_row_count=1,
        result_row_count=1,
    )

    report = build_report(
        template=_template(),
        input_dir="/data",
        dry_run=False,
        strict=False,
        file_load_errors=[],
        file_validation_results=[fvr],
        aggregation_result=agg,
        output_path="/data/ergebnis.xlsx",
        timestamp=_TIMESTAMP,
    )

    assert report.status == "success"
    assert report.total_warnings == 0

    md = render_markdown(report)
    html = render_html(report)
    assert "Erfolg" in md
    assert 'class="status-success"' in html
    assert "gut.csv" in md


# ---------------------------------------------------------------------------
# Fall: Warnung (unbekannte Spalte)
# ---------------------------------------------------------------------------


def test_warning_case_status_and_rendering():
    fvr = FileValidationResult(
        filename="warn.csv",
        df=pd.DataFrame({"Artikelnummer": ["A1"], "Laufmeter": [5.0]}),
        warnings=[
            ColumnIssue(column="Kommentar", message="Unbekannte Spalte 'Kommentar'.")
        ],
    )
    agg = AggregationResult(
        df=pd.DataFrame({"Artikelnummer": ["A1"], "Laufmeter": [5.0]}),
        sums_before={"Laufmeter": 5.0},
        sums_after={"Laufmeter": 5.0},
        input_row_count=1,
        result_row_count=1,
    )

    report = build_report(
        template=_template(),
        input_dir="/data",
        dry_run=False,
        strict=False,
        file_load_errors=[],
        file_validation_results=[fvr],
        aggregation_result=agg,
        output_path="/data/ergebnis.xlsx",
        timestamp=_TIMESTAMP,
    )

    assert report.status == "success_with_warnings"
    assert report.total_warnings == 1

    md = render_markdown(report)
    assert "Unbekannte Spalte 'Kommentar'" in md

    html = render_html(report)
    assert 'class="status-success_with_warnings"' in html


# ---------------------------------------------------------------------------
# Fall: Fehler + dry-run + strict
# ---------------------------------------------------------------------------


def test_error_case_with_dry_run_and_strict():
    fvr = FileValidationResult(
        filename="kaputt.csv",
        errors=[
            ColumnIssue(column="Laufmeter", message="Pflichtspalte 'Laufmeter' fehlt.")
        ],
    )

    report = build_report(
        template=_template(),
        input_dir="/data",
        dry_run=True,
        strict=True,
        file_load_errors=[
            FileLoadError("Datei 'defekt.xlsx' konnte nicht gelesen werden.")
        ],
        file_validation_results=[fvr],
        aggregation_result=None,
        output_path="/data/ergebnis.xlsx",
        timestamp=_TIMESTAMP,
    )

    assert report.status == "error"

    md = render_markdown(report)
    assert "DRY RUN" in md
    assert "dry-run, strict" in md
    assert "defekt.xlsx" in md
    assert "Pflichtspalte 'Laufmeter' fehlt" in md

    html = render_html(report)
    assert "DRY RUN" in html
    assert 'class="status-error"' in html


# ---------------------------------------------------------------------------
# add_result_validation_errors – Ebene-3-Fehler nachträglich eintragen
# ---------------------------------------------------------------------------


def test_add_result_validation_errors_escalates_to_error_status():
    fvr = FileValidationResult(
        filename="gut.csv",
        df=pd.DataFrame({"Artikelnummer": ["A1"], "Laufmeter": [10.5]}),
    )
    report = build_report(
        template=_template(),
        input_dir="/data",
        dry_run=False,
        strict=False,
        file_load_errors=[],
        file_validation_results=[fvr],
        aggregation_result=None,
        output_path=None,
        timestamp=_TIMESTAMP,
    )
    assert report.status == "success"

    result_validation = ResultValidationResult(
        errors=[ResultIssue(message="Duplikate nach Aggregation gefunden.")]
    )
    add_result_validation_errors(report, result_validation)

    assert report.status == "error"
    assert "Duplikate nach Aggregation gefunden." in report.abort_errors


# ---------------------------------------------------------------------------
# write_report – beide Dateien werden geschrieben, keine Doppel-Endung
# ---------------------------------------------------------------------------


def test_write_report_creates_both_files(tmp_path):
    fvr = FileValidationResult(
        filename="gut.csv", df=pd.DataFrame({"Artikelnummer": ["A1"]})
    )
    report = build_report(
        template=_template(),
        input_dir="/data",
        dry_run=False,
        strict=False,
        file_load_errors=[],
        file_validation_results=[fvr],
        aggregation_result=None,
        output_path=None,
        timestamp=_TIMESTAMP,
    )

    base = tmp_path / "report"
    md_path, html_path = write_report(report, base)

    assert md_path.exists()
    assert html_path.exists()
    assert md_path.read_text(encoding="utf-8") == render_markdown(report)
    assert html_path.read_text(encoding="utf-8") == render_html(report)


def test_write_report_avoids_double_extension(tmp_path):
    fvr = FileValidationResult(
        filename="gut.csv", df=pd.DataFrame({"Artikelnummer": ["A1"]})
    )
    report = build_report(
        template=_template(),
        input_dir="/data",
        dry_run=False,
        strict=False,
        file_load_errors=[],
        file_validation_results=[fvr],
        aggregation_result=None,
        output_path=None,
        timestamp=_TIMESTAMP,
    )

    base = tmp_path / "report.md"  # Nutzer gibt versehentlich schon .md an
    md_path, html_path = write_report(report, base)

    assert md_path.name == "report.md"
    assert html_path.name == "report.html"
