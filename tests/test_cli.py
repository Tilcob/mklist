"""Tests für Phase 8 – CLI (cli.py).

Testfokus laut Implementierungsplan: End-to-End-Test mit einem kleinen
Beispielordner (2-3 Testdateien, bewusst mit einer bekannten Warnung und
einem bekannten Duplikat), Prüfung von Konsolenausgabe, Exit Code,
erzeugter .xlsx und beiden Report-Dateien.

Diese Tests benötigen pydantic UND pandera gemeinsam (die komplette
Pipeline) und konnten daher in der Entwicklungsumgebung nicht ausgeführt
werden (siehe vorherige Phasen: pandera stand dort nicht zur Verfügung).
Bitte als Erstes lokal laufen lassen.
"""

import json

import pandas as pd
import pytest
from click.testing import CliRunner

from mklist.cli import cli


def _write_template(path, **overrides):
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
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def _write_csv(path, rows, header="Artikelnummer;Farbe;Laufmeter"):
    lines = [header] + rows
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# mklist run – Erfolg
# ---------------------------------------------------------------------------


def test_run_success_exit_code_0(tmp_path):
    template_path = _write_template(tmp_path / "template.json")
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _write_csv(input_dir / "a.csv", ["A1;rot;10.5", "A2;blau;3.0"])

    runner = CliRunner()
    result = runner.invoke(
        cli, ["run", "--template", str(template_path), "--input-dir", str(input_dir)]
    )

    assert result.exit_code == 0, result.output
    assert "Status: success" in result.output

    output_files = list(input_dir.glob("ergebnis_*.xlsx"))
    assert len(output_files) == 1
    df = pd.read_excel(output_files[0])
    assert set(df["Artikelnummer"]) == {"A1", "A2"}

    assert list(input_dir.glob("report_*.md"))
    assert list(input_dir.glob("report_*.html"))


# ---------------------------------------------------------------------------
# mklist run – Duplikate werden korrekt zusammengeführt
# ---------------------------------------------------------------------------


def test_run_merges_duplicates_across_files(tmp_path):
    template_path = _write_template(tmp_path / "template.json")
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _write_csv(input_dir / "a.csv", ["A1;rot;10.5"])
    _write_csv(input_dir / "b.csv", ["A1;rot;5.25", "A2;blau;3.0"])

    runner = CliRunner()
    result = runner.invoke(
        cli, ["run", "--template", str(template_path), "--input-dir", str(input_dir)]
    )

    assert result.exit_code == 0, result.output
    output_files = list(input_dir.glob("ergebnis_*.xlsx"))
    df = pd.read_excel(output_files[0])

    assert len(df) == 2  # A1/rot zusammengefasst, A2/blau einzeln
    row_a1 = df[df["Artikelnummer"] == "A1"].iloc[0]
    assert row_a1["Laufmeter"] == 15.75


# ---------------------------------------------------------------------------
# mklist run – Warnung (unbekannte Spalte) -> Exit Code 2
# ---------------------------------------------------------------------------


def test_run_unknown_column_warning_exit_code_2(tmp_path):
    template_path = _write_template(tmp_path / "template.json")
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _write_csv(
        input_dir / "a.csv",
        ["A1;rot;10.5;Bemerkung1"],
        header="Artikelnummer;Farbe;Laufmeter;Kommentar",
    )

    runner = CliRunner()
    result = runner.invoke(
        cli, ["run", "--template", str(template_path), "--input-dir", str(input_dir)]
    )

    assert result.exit_code == 2, result.output
    assert "Warnungen" in result.output
    # Ausgabedatei wird trotz Warnung geschrieben (Warnung != Abbruch-Fehler)
    assert list(input_dir.glob("ergebnis_*.xlsx"))


def test_run_unknown_column_warning_appears_in_report(tmp_path):
    template_path = _write_template(tmp_path / "template.json")
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _write_csv(
        input_dir / "a.csv",
        ["A1;rot;10.5;xyz"],
        header="Artikelnummer;Farbe;Laufmeter;Kommentar",
    )

    runner = CliRunner()
    runner.invoke(
        cli, ["run", "--template", str(template_path), "--input-dir", str(input_dir)]
    )

    report_md = list(input_dir.glob("report_*.md"))[0]
    content = report_md.read_text(encoding="utf-8")
    assert "Kommentar" in content


# ---------------------------------------------------------------------------
# mklist run – fehlende Pflichtspalte -> Exit Code 1
# ---------------------------------------------------------------------------


def test_run_missing_required_column_exit_code_1(tmp_path):
    template_path = _write_template(tmp_path / "template.json")
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _write_csv(
        input_dir / "a.csv", ["A1;rot"], header="Artikelnummer;Farbe"
    )  # Laufmeter fehlt

    runner = CliRunner()
    result = runner.invoke(
        cli, ["run", "--template", str(template_path), "--input-dir", str(input_dir)]
    )

    assert result.exit_code == 1, result.output
    # Bei Abbruch-Fehler wird KEINE Ausgabedatei geschrieben
    assert not list(input_dir.glob("ergebnis_*.xlsx"))


def test_run_missing_required_column_does_not_merge_other_valid_files(tmp_path):
    # Auch wenn eine ANDERE Datei fehlerfrei waere, darf bei einem
    # Abbruch-Fehler in irgendeiner Datei NICHTS zusammengefuehrt werden
    # (siehe cli.py Moduldoku: kein teilweises Zusammenfuehren).
    template_path = _write_template(tmp_path / "template.json")
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _write_csv(input_dir / "gut.csv", ["A1;rot;10.5"])
    _write_csv(input_dir / "kaputt.csv", ["A2;blau"], header="Artikelnummer;Farbe")

    runner = CliRunner()
    result = runner.invoke(
        cli, ["run", "--template", str(template_path), "--input-dir", str(input_dir)]
    )

    assert result.exit_code == 1
    assert not list(input_dir.glob("ergebnis_*.xlsx"))


# ---------------------------------------------------------------------------
# mklist run – --dry-run
# ---------------------------------------------------------------------------


def test_run_dry_run_does_not_write_output_but_writes_report(tmp_path):
    template_path = _write_template(tmp_path / "template.json")
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _write_csv(input_dir / "a.csv", ["A1;rot;10.5"])

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "run",
            "--template",
            str(template_path),
            "--input-dir",
            str(input_dir),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.output
    assert not list(input_dir.glob("ergebnis_*.xlsx"))
    report_md = list(input_dir.glob("report_*.md"))
    assert report_md
    assert "DRY RUN" in report_md[0].read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# mklist run – --strict eskaliert Warnungen zu Fehlern
# ---------------------------------------------------------------------------


def test_run_strict_escalates_warning_to_error(tmp_path):
    template_path = _write_template(tmp_path / "template.json")
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _write_csv(
        input_dir / "a.csv",
        ["A1;rot;10.5;xyz"],
        header="Artikelnummer;Farbe;Laufmeter;Kommentar",
    )

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "run",
            "--template",
            str(template_path),
            "--input-dir",
            str(input_dir),
            "--strict",
        ],
    )

    assert result.exit_code == 1, result.output
    assert not list(input_dir.glob("ergebnis_*.xlsx"))


# ---------------------------------------------------------------------------
# mklist run – benutzerdefinierte --output/--report-Pfade
# ---------------------------------------------------------------------------


def test_run_respects_explicit_output_and_report_paths(tmp_path):
    template_path = _write_template(tmp_path / "template.json")
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    _write_csv(input_dir / "a.csv", ["A1;rot;10.5"])

    custom_output = tmp_path / "custom_ergebnis.xlsx"
    custom_report = tmp_path / "custom_report"

    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "run",
            "--template",
            str(template_path),
            "--input-dir",
            str(input_dir),
            "--output",
            str(custom_output),
            "--report",
            str(custom_report),
        ],
    )

    assert result.exit_code == 0, result.output
    assert custom_output.exists()
    assert (tmp_path / "custom_report.md").exists()
    assert (tmp_path / "custom_report.html").exists()


# ---------------------------------------------------------------------------
# mklist validate-template
# ---------------------------------------------------------------------------


def test_validate_template_valid(tmp_path):
    template_path = _write_template(tmp_path / "template.json")

    runner = CliRunner()
    result = runner.invoke(cli, ["validate-template", "--template", str(template_path)])

    assert result.exit_code == 0
    assert "gültig" in result.output


def test_validate_template_invalid(tmp_path):
    template_path = tmp_path / "template.json"
    template_path.write_text(
        json.dumps({"template_name": "x", "version": "1.0"}), encoding="utf-8"
    )  # unvollstaendig

    runner = CliRunner()
    result = runner.invoke(cli, ["validate-template", "--template", str(template_path)])

    assert result.exit_code == 1


# ---------------------------------------------------------------------------
# mklist list-templates
# ---------------------------------------------------------------------------


def test_list_templates_shows_name_and_version(tmp_path):
    template_dir = tmp_path / "templates"
    template_dir.mkdir()
    _write_template(template_dir / "a.json", template_name="Vorlage A", version="1.0")
    _write_template(template_dir / "b.json", template_name="Vorlage B", version="2.0")

    runner = CliRunner()
    result = runner.invoke(cli, ["list-templates", "--template-dir", str(template_dir)])

    assert result.exit_code == 0
    assert "Vorlage A" in result.output
    assert "Vorlage B" in result.output


def test_list_templates_empty_dir(tmp_path):
    template_dir = tmp_path / "templates"
    template_dir.mkdir()

    runner = CliRunner()
    result = runner.invoke(cli, ["list-templates", "--template-dir", str(template_dir)])

    assert result.exit_code == 0
    assert "Keine Vorlagen" in result.output
