"""The variable tree, checked against the structures that appear in real
Alchemer exports. The fixture reproduces each one."""
from __future__ import annotations

import pandas as pd
import pytest

from app.core.variables import build_variables, classify_column, distinct_values

FIXTURE = "tests/fixtures/synthetic_survey.csv"


@pytest.fixture(scope="module")
def specs():
    df = pd.read_csv(FIXTURE)
    return {s.var_key: s for s in build_variables(df)}


def test_metadata_and_weight_column(specs):
    assert specs["meta:Response ID"].kind == "meta"
    # weight_demog is the house convention and gets its own kind.
    assert specs["meta:weight_demog"].kind == "weight"


def test_open_text_age_is_numeric(specs):
    assert specs["numeric:75"].kind == "numeric"


def test_single_response_keeps_questionnaire_order(specs):
    v = specs["single:401"]
    assert v.kind == "single"
    assert v.columns == ["401: How much do you trust the government?"]
    assert "Trust a great deal" in v.value_labels


def test_specify_followup_does_not_turn_a_single_into_a_matrix(specs):
    """The regression this exists to prevent: ethnic group is one categorical
    column plus a free-text follow-up, not a six-item matrix."""
    assert specs["single:29"].kind == "single"
    assert len(specs["single:29"].columns) == 1
    assert specs["text:29:Any other ethnic group (Please describe)"].kind == "text"


def test_multi_punch_is_one_variable_over_many_columns(specs):
    v = specs["multi:163"]
    assert v.kind == "multi"
    assert len(v.columns) == 4  # the specify column is excluded
    assert set(v.value_labels) == {"Buddhism", "Christianity", "Islam", "No religion/Atheism"}


def test_specify_column_excluded_from_multi_punch_options(specs):
    assert "Other (Please specify) (text)" not in specs["multi:163"].value_labels
    assert specs["text:163:Other (Please specify) (text)"].kind == "text"


def test_matrix_becomes_a_parent_plus_items(specs):
    parent = specs["matrix:481"]
    assert parent.kind == "matrix_group"
    assert len(parent.columns) == 3
    item = specs["matrix_item:481:Andy Burnham"]
    assert item.kind == "matrix_item"
    assert item.parent_key == "matrix:481"
    assert "Very favourable" in item.value_labels


def test_routed_empty_question_is_flagged_not_crashed(specs):
    v = specs["multi:595"]
    assert v.notes and "routed" in v.notes[0].lower()


def test_every_column_is_accounted_for():
    df = pd.read_csv(FIXTURE)
    covered = {c for s in build_variables(df) for c in s.columns}
    assert covered == set(df.columns)


def test_missing_tokens_ignored_when_listing_values():
    s = pd.Series(["Yes", "No", "", "N/A", None, "null", "Yes"])
    assert distinct_values(s) == ["Yes", "No"]


def test_classify_empty_column():
    assert classify_column(pd.Series([None, "", "NA"]))[0] == "empty"


def test_high_cardinality_numeric_is_numeric_not_categorical():
    assert classify_column(pd.Series(range(100)))[0] == "numeric"


def test_low_cardinality_numeric_stays_categorical():
    """A 1-5 scale coded numerically is a category, not a measurement."""
    assert classify_column(pd.Series([1, 2, 3, 4, 5] * 20))[0] == "single"
