"""Tests für Phase 1 – Vorlagen-Modell (template.py).

Je ein Testfall pro Cross-Field-Regel (bewusst kaputte Vorlagen) sowie ein
Testfall für extra="forbid" (Tippfehler im Feldnamen). Siehe Implementierungsplan
Phase 1, Testfokus.
"""

import json

import pytest
from pydantic import ValidationError

from mklist.template import TemplateConfig, TemplateLoadError, load_template


def _valid_template_dict() -> dict:
    """Eine minimal gültige Vorlage als Ausgangspunkt für die Testfälle.
    Jeder Testfall nimmt eine Kopie und macht sie gezielt an einer Stelle
    ungültig."""
    return {
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
        "validation_rules": {"Laufmeter": {"min": 0}},
    }


def test_valid_template_loads_successfully():
    """Eine korrekte Vorlage muss ohne Fehler geladen werden können."""
    config = TemplateConfig.model_validate(_valid_template_dict())
    assert config.template_name == "Test-Vorlage"
    assert len(config.duplicate_keys) == 2


# -- Regel 1: duplicate_keys müssen in required_columns vorkommen -----------


def test_rule1_duplicate_key_not_in_required_columns():
    data = _valid_template_dict()
    data["duplicate_keys"] = ["Artikelnummer", "Charge"]  # "Charge" existiert nicht
    with pytest.raises(ValidationError, match="duplicate_keys.*Charge"):
        TemplateConfig.model_validate(data)


# -- Regel 2: column_types-Keys müssen in required_columns vorkommen --------


def test_rule2_column_type_not_in_required_columns():
    data = _valid_template_dict()
    data["input"]["column_types"]["Lieferant"] = "string"  # nicht in required_columns
    with pytest.raises(ValidationError, match="column_types.*Lieferant"):
        TemplateConfig.model_validate(data)


# -- Regel 3: aggregate.column muss existieren und bei sum/mean numerisch sein --


def test_rule3_aggregate_column_not_in_required_columns():
    data = _valid_template_dict()
    data["aggregate"] = [{"column": "Unbekannt", "method": "sum"}]
    with pytest.raises(ValidationError, match="aggregate.*Unbekannt"):
        TemplateConfig.model_validate(data)


def test_rule3_aggregate_sum_on_non_numeric_column():
    data = _valid_template_dict()
    # "Farbe" ist laut column_types "string" -> sum ergibt keinen Sinn
    data["aggregate"] = [{"column": "Farbe", "method": "sum"}]
    with pytest.raises(ValidationError, match="numerisch"):
        TemplateConfig.model_validate(data)


# -- Regel 4: output.sort_by/columns_order müssen im Ergebnis existieren ----


def test_rule4_columns_order_references_unknown_column():
    data = _valid_template_dict()
    data["output"]["columns_order"] = ["Artikelnummer", "Farbe", "Kommentar"]
    with pytest.raises(ValidationError, match="columns_order.*Kommentar"):
        TemplateConfig.model_validate(data)


def test_rule4_sort_by_references_unknown_column():
    data = _valid_template_dict()
    data["output"]["sort_by"] = ["Kommentar"]
    with pytest.raises(ValidationError, match="sort_by.*Kommentar"):
        TemplateConfig.model_validate(data)


# -- Regel 5: validation_rules-Keys müssen numerisch sein -------------------


def test_rule5_validation_rule_on_non_numeric_column():
    data = _valid_template_dict()
    data["validation_rules"] = {"Farbe": {"min": 0}}  # "Farbe" ist string
    with pytest.raises(ValidationError, match="validation_rules.*Farbe"):
        TemplateConfig.model_validate(data)


# -- extra="forbid": unbekannte Felder sind ein Fehler -----------------------


def test_unknown_top_level_field_is_rejected():
    data = _valid_template_dict()
    data["duplicate_key"] = ["Artikelnummer"]  # Tippfehler statt duplicate_keys
    with pytest.raises(ValidationError):
        TemplateConfig.model_validate(data)


def test_unknown_nested_field_is_rejected():
    data = _valid_template_dict()
    data["input"]["required_column"] = ["Artikelnummer"]  # Tippfehler
    with pytest.raises(ValidationError):
        TemplateConfig.model_validate(data)


# -- duplicate_keys: mindestens 1 Element -----------------------------------


def test_duplicate_keys_must_have_at_least_one_element():
    data = _valid_template_dict()
    data["duplicate_keys"] = []
    with pytest.raises(ValidationError):
        TemplateConfig.model_validate(data)


# -- load_template(): Datei-Ebene ------------------------------------------


def test_load_template_missing_file(tmp_path):
    missing = tmp_path / "does_not_exist.json"
    with pytest.raises(TemplateLoadError, match="nicht gefunden"):
        load_template(missing)


def test_load_template_invalid_json(tmp_path):
    broken = tmp_path / "broken.json"
    broken.write_text("{ this is not valid json", encoding="utf-8")
    with pytest.raises(TemplateLoadError, match="kein gültiges JSON"):
        load_template(broken)


def test_load_template_valid_file(tmp_path):
    valid = tmp_path / "valid.json"
    valid.write_text(json.dumps(_valid_template_dict()), encoding="utf-8")
    config = load_template(valid)
    assert config.template_name == "Test-Vorlage"


def test_load_template_invalid_content_reports_field_path(tmp_path):
    data = _valid_template_dict()
    data["duplicate_keys"] = ["Charge"]
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(TemplateLoadError, match="Charge"):
        load_template(invalid)
