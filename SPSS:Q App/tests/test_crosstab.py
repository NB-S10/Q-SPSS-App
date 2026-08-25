"""The crosstab engine, checked against independently computed numbers.

Bases are the thing that goes wrong, so most of these are base tests.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from app.core.crosstab import (
    TableSpecError,
    build_view,
    column_letters,
    compute_table,
)
from app.core.variables import build_variables
from app.core.weights import resolve_weights

FIXTURE = "tests/fixtures/synthetic_survey.csv"
TRUST_COL = "401: How much do you trust the government?"
GENDER_COL = "377: Which of the following best describes how you think of yourself?"


@pytest.fixture
def df():
    return pd.read_csv(FIXTURE)


@pytest.fixture
def specs(df):
    out = {s.var_key: s for s in build_variables(df)}
    for s in out.values():
        s.missing_codes = []
    return out


@pytest.fixture
def unweighted(df):
    return resolve_weights(df, "unweighted")


def _pcts(block, column=0):
    return {r["label"]: r["cells"][column]["col_pct"] for r in block["rows"]}


# ---------------------------------------------------------------- basics


def test_column_percentages_match_pandas(df, specs, unweighted):
    table = compute_table(
        df, [specs["single:401"]], [{"var_key": "single:377"}], [specs["single:377"]],
        unweighted,
    )
    expected = pd.crosstab(df[TRUST_COL], df[GENDER_COL], normalize="columns")
    male_index = [c["label"] for c in table["columns"]].index("Male")
    got = _pcts(table["blocks"][0], male_index)
    for category, value in expected["Male"].items():
        assert got[category] == pytest.approx(value)


def test_column_percentages_sum_to_one_for_single_response(df, specs, unweighted):
    table = compute_table(df, [specs["single:401"]], [], [], unweighted)
    assert sum(_pcts(table["blocks"][0]).values()) == pytest.approx(1.0)


def test_banner_bases_sum_to_the_total_base_for_a_single_response_banner(
    df, specs, unweighted
):
    table = compute_table(
        df, [specs["single:401"]], [{"var_key": "single:377"}], [specs["single:377"]],
        unweighted,
    )
    bases = table["blocks"][0]["bases_unweighted"]
    assert sum(bases[1:]) == pytest.approx(bases[0])


def test_total_column_comes_first_and_has_no_letter(df, specs, unweighted):
    table = compute_table(
        df, [specs["single:401"]], [{"var_key": "single:377"}], [specs["single:377"]],
        unweighted,
    )
    assert table["columns"][0]["key"] == "total"
    assert table["columns"][0]["letter"] == ""
    assert [c["letter"] for c in table["columns"][1:]] == ["a", "b", "c"]


def test_categories_follow_the_variables_declared_order(df, specs, unweighted):
    trust = specs["single:401"]
    trust.category_order = list(reversed(trust.category_order))
    table = compute_table(df, [trust], [], [], unweighted)
    assert [r["label"] for r in table["blocks"][0]["rows"]] == trust.category_order


# ---------------------------------------------------------------- multi-punch


def test_multi_punch_base_is_respondents_not_selections(df, specs, unweighted):
    """The single most common way a home-made tables tool gets it wrong."""
    table = compute_table(df, [specs["multi:163"]], [], [], unweighted)
    block = table["blocks"][0]

    columns = [c for c in df.columns if c.startswith("163: ") and "specify" not in c.lower()]
    selected = df[columns].notna()
    assert block["bases_unweighted"][0] == pytest.approx(selected.any(axis=1).sum())
    assert block["bases_unweighted"][0] != selected.sum().sum()


def test_multi_punch_percentages_may_exceed_one_hundred(df, specs, unweighted):
    table = compute_table(df, [specs["multi:163"]], [], [], unweighted)
    assert sum(_pcts(table["blocks"][0]).values()) > 1.0


def test_multi_punch_option_labels_come_from_headers_not_data(df, specs):
    """An option nobody selected has no value in the data to read a label from,
    so labels must come from the column header."""
    view = build_view(specs["multi:595"], df)  # routed question, entirely blank
    assert view.categories == ["Oldest child", "Second oldest child"]
    assert all(mask.sum() == 0 for mask in view.masks.values())
    assert view.base_mask.sum() == 0


def test_multi_punch_on_the_banner_axis_double_counts_respondents(df, specs, unweighted):
    """A respondent picking three religions appears in three banner columns, so
    the banner bases legitimately sum past the total base."""
    table = compute_table(
        df, [specs["single:401"]], [{"var_key": "multi:163"}], [specs["multi:163"]],
        unweighted,
    )
    bases = table["blocks"][0]["bases_unweighted"]
    assert sum(bases[1:]) > bases[0]


def test_multi_punch_on_both_axes_is_allowed(df, specs, unweighted):
    """The browser app refused this outright."""
    table = compute_table(
        df, [specs["multi:163"]], [{"var_key": "multi:163"}], [specs["multi:163"]],
        unweighted,
    )
    assert table["blocks"][0]["rows"]


def test_unselected_tokens_are_not_counted_as_selections():
    """Exports from outside Alchemer write 0/No rather than leaving blanks."""
    frame = pd.DataFrame({
        "9: Apples:Which do you like?": ["Apples", "No", "0", None, "Apples"],
        "9: Pears:Which do you like?": ["Pears", "Pears", "false", "", None],
    })
    spec = next(s for s in build_variables(frame) if s.kind == "multi")
    spec.missing_codes = []
    view = build_view(spec, frame)
    assert view.masks["Apples"].tolist() == [True, False, False, False, True]
    assert view.masks["Pears"].tolist() == [True, True, False, False, False]
    assert view.base_mask.tolist() == [True, True, False, False, True]


# ---------------------------------------------------------------- bases


def test_missing_codes_shrink_the_base_and_move_every_percentage(df, specs, unweighted):
    trust = specs["single:401"]
    before = compute_table(df, [trust], [], [], unweighted)["blocks"][0]
    trust.missing_codes = ["Don't know"]
    after = compute_table(df, [trust], [], [], unweighted)["blocks"][0]

    assert after["bases_unweighted"][0] < before["bases_unweighted"][0]
    assert _pcts(after)["Not at all"] > _pcts(before)["Not at all"]
    # The excluded row is still shown, flagged, so the reader can see it exists.
    assert any(r["excluded"] and r["label"] == "Don't know" for r in after["rows"])


def test_percentages_still_sum_to_one_over_the_included_categories(df, specs, unweighted):
    trust = specs["single:401"]
    trust.missing_codes = ["Don't know"]
    block = compute_table(df, [trust], [], [], unweighted)["blocks"][0]
    included = [r["cells"][0]["col_pct"] for r in block["rows"] if not r["excluded"]]
    assert sum(included) == pytest.approx(1.0)


def test_base_rule_total_ignores_missing_codes(df, specs, unweighted):
    trust = specs["single:401"]
    trust.missing_codes = ["Don't know"]
    block = compute_table(df, [trust], [], [], unweighted, base_rule="total")["blocks"][0]
    assert block["bases_unweighted"][0] == len(df)


def test_base_is_recomputed_per_banner_column(df, specs, unweighted):
    """Whether a respondent is in the base depends on the row variable AND the
    column, so bases belong to the block rather than the table."""
    table = compute_table(
        df, [specs["multi:163"], specs["single:401"]],
        [{"var_key": "single:377"}], [specs["single:377"]], unweighted,
    )
    religion, trust = table["blocks"]
    assert religion["bases_unweighted"] != trust["bases_unweighted"]


def test_a_question_nobody_answered_gives_no_percentages(df, specs, unweighted):
    block = compute_table(df, [specs["multi:595"]], [], [], unweighted)["blocks"][0]
    assert block["bases_unweighted"][0] == 0
    assert all(r["cells"][0]["col_pct"] is None for r in block["rows"])


# ---------------------------------------------------------------- weighting


def test_weighted_base_is_the_sum_of_weights(df, specs):
    weights = resolve_weights(df, "column", "weight_demog")
    block = compute_table(df, [specs["single:401"]], [], [], weights)["blocks"][0]
    assert block["bases_weighted"][0] == pytest.approx(weights.sum())
    assert block["bases_unweighted"][0] == len(df)


def test_weighting_changes_the_percentages(df, specs):
    plain = compute_table(df, [specs["single:401"]], [], [],
                          resolve_weights(df, "unweighted"))["blocks"][0]
    weighted = compute_table(df, [specs["single:401"]], [], [],
                             resolve_weights(df, "column", "weight_demog"))["blocks"][0]
    assert _pcts(plain) != _pcts(weighted)


def test_unweighted_is_the_same_arithmetic_as_all_ones(df, specs):
    """Weighting must not be a separate code path, or the two drift apart."""
    a = compute_table(df, [specs["single:401"]], [], [],
                      resolve_weights(df, "unweighted"))["blocks"][0]
    b = compute_table(df, [specs["single:401"]], [], [],
                      np.ones(len(df)))["blocks"][0]
    assert _pcts(a) == _pcts(b)


def test_mismatched_weight_vector_is_refused(df, specs):
    with pytest.raises(ValueError, match="doesn't match"):
        compute_table(df, [specs["single:401"]], [], [], np.ones(5))


# ---------------------------------------------------------------- filters


def test_filter_restricts_the_base(df, specs, unweighted):
    table = compute_table(
        df, [specs["single:401"]], [], [], unweighted,
        filter_clauses=[{"var_key": "single:377", "categories": ["Female"]}],
        filter_variables=[specs["single:377"]],
    )
    assert table["n_filtered"] == int((df[GENDER_COL] == "Female").sum())
    assert table["blocks"][0]["bases_unweighted"][0] == table["n_filtered"]
    assert table["filter"]


def test_filter_clauses_combine_with_and(df, specs, unweighted):
    table = compute_table(
        df, [specs["single:401"]], [], [], unweighted,
        filter_clauses=[
            {"var_key": "single:377", "categories": ["Female"]},
            {"var_key": "single:378", "categories": ["London"]},
        ],
        filter_variables=[specs["single:377"], specs["single:378"]],
    )
    expected = ((df[GENDER_COL] == "Female")
                & (df["378: In what region of the UK do you live"] == "London")).sum()
    assert table["n_filtered"] == expected


def test_a_filter_on_a_variable_that_was_not_supplied_is_refused(df, specs, unweighted):
    """Skipping it would return unfiltered numbers that look filtered."""
    with pytest.raises(TableSpecError, match="isn't in this dataset"):
        compute_table(
            df, [specs["single:401"]], [], [], unweighted,
            filter_clauses=[{"var_key": "single:377", "categories": ["Female"]}],
        )


def test_an_empty_filter_is_refused_rather_than_ignored(df, specs, unweighted):
    with pytest.raises(TableSpecError, match="keep everybody"):
        compute_table(
            df, [specs["single:401"]], [], [], unweighted,
            filter_clauses=[{"var_key": "single:377", "categories": []}],
            filter_variables=[specs["single:377"]],
        )


def test_a_mistyped_filter_category_is_refused(df, specs, unweighted):
    with pytest.raises(TableSpecError, match="Not a category"):
        compute_table(
            df, [specs["single:401"]], [], [], unweighted,
            filter_clauses=[{"var_key": "single:377", "categories": ["Femail"]}],
            filter_variables=[specs["single:377"]],
        )


def test_unknown_banner_variable_is_refused(df, specs, unweighted):
    with pytest.raises(TableSpecError, match="Banner variable"):
        compute_table(df, [specs["single:401"]], [{"var_key": "single:999"}], [], unweighted)


def test_table_needs_a_row_variable(df, unweighted):
    with pytest.raises(TableSpecError, match="at least one row variable"):
        compute_table(df, [], [], [], unweighted)


# ---------------------------------------------------------------- derived stats


def test_row_percentages_span_a_banner_group_and_exclude_total(df, specs, unweighted):
    table = compute_table(
        df, [specs["single:401"]], [{"var_key": "single:377"}], [specs["single:377"]],
        unweighted,
    )
    for row in table["blocks"][0]["rows"]:
        within_group = [c["row_pct"] for c in row["cells"][1:]]
        assert sum(within_group) == pytest.approx(1.0)
    assert table["blocks"][0]["rows"][0]["cells"][0]["row_pct"] is None


def test_index_is_one_hundred_against_the_total_column(df, specs, unweighted):
    table = compute_table(
        df, [specs["single:401"]], [{"var_key": "single:377"}], [specs["single:377"]],
        unweighted,
    )
    for row in table["blocks"][0]["rows"]:
        assert row["cells"][0]["index"] == 100


def test_letters_extend_past_twenty_six_rather_than_recycling():
    letters = column_letters(30)
    assert letters[:3] == ["a", "b", "c"]
    assert letters[25:28] == ["z", "aa", "ab"]
    assert len(set(letters)) == 30


# ---------------------------------------------------------------- single options


def test_each_multi_punch_option_is_also_a_variable_of_its_own(specs):
    keys = {s.var_key for s in specs.values()}
    assert "multi:163" in keys
    for option in ["Buddhism", "Christianity", "Islam", "No religion/Atheism"]:
        assert f"multi_item:163:{option}" in keys


def test_option_variables_are_children_of_their_question(specs):
    item = specs["multi_item:163:Christianity"]
    assert item.parent_key == "multi:163"
    assert item.kind == "multi_item"
    assert item.label == "Christianity"
    assert item.columns == [c for c in specs["multi:163"].columns if "Christianity" in c]


def test_an_option_on_its_own_matches_its_row_in_the_combined_table(df, specs, unweighted):
    """Two views of the same data must agree, or the tool can't be trusted.
    The option is based on everyone who answered the question, not on the people
    who picked it -- otherwise it would read 100% by construction.
    """
    combined = compute_table(df, [specs["multi:163"]], [], [], unweighted)["blocks"][0]
    combined_pcts = {r["label"]: r["cells"][0]["col_pct"] for r in combined["rows"]}

    for option, expected in combined_pcts.items():
        block = compute_table(
            df, [specs[f"multi_item:163:{option}"]], [], [], unweighted
        )["blocks"][0]
        selected = next(r for r in block["rows"] if r["label"] == "Selected")
        assert selected["cells"][0]["col_pct"] == pytest.approx(expected)
        assert block["bases_unweighted"][0] == pytest.approx(combined["bases_unweighted"][0])


def test_option_variable_has_selected_and_not_selected_summing_to_one(df, specs, unweighted):
    block = compute_table(
        df, [specs["multi_item:163:Christianity"]], [], [], unweighted
    )["blocks"][0]
    assert [r["label"] for r in block["rows"]] == ["Selected", "Not selected"]
    assert sum(r["cells"][0]["col_pct"] for r in block["rows"]) == pytest.approx(1.0)


def test_a_single_option_can_be_used_as_a_table_column(df, specs, unweighted):
    table = compute_table(
        df, [specs["single:401"]],
        [{"var_key": "multi_item:163:Christianity"}],
        [specs["multi_item:163:Christianity"]], unweighted,
    )
    assert [c["label"] for c in table["columns"]] == ["Total", "Selected", "Not selected"]
    bases = table["blocks"][0]["bases_unweighted"]
    # Selected and Not selected partition the question's base, so they cannot
    # sum past the total.
    assert bases[1] + bases[2] <= bases[0]


# ---------------------------------------------------------------- hiding rows


def test_hiding_a_row_does_not_change_the_base_or_the_percentages(df, specs, unweighted):
    """Hiding is presentation; excluding from the base is arithmetic. Conflating
    them would silently restate every percentage in the table."""
    trust = specs["single:401"]
    full = compute_table(df, [trust], [], [], unweighted)["blocks"][0]
    kept = [c for c in full["all_categories"] if c != "Don't know"]
    trimmed = compute_table(
        df, [trust], [], [], unweighted, row_categories={"single:401": kept}
    )["blocks"][0]

    assert trimmed["bases_unweighted"] == full["bases_unweighted"]
    before = {r["label"]: r["cells"][0]["col_pct"] for r in full["rows"]}
    after = {r["label"]: r["cells"][0]["col_pct"] for r in trimmed["rows"]}
    for label, value in after.items():
        assert value == pytest.approx(before[label])


def test_visible_rows_may_sum_to_less_than_one_hundred_when_a_row_is_hidden(
    df, specs, unweighted
):
    kept = ["Trust a great deal", "Trust a fair amount", "Not very much", "Not at all"]
    block = compute_table(
        df, [specs["single:401"]], [], [], unweighted,
        row_categories={"single:401": kept},
    )["blocks"][0]
    assert sum(r["cells"][0]["col_pct"] for r in block["rows"]) < 1.0
    assert block["hidden_categories"] == ["Don't know"]


def test_hidden_rows_are_reported_so_the_reader_knows_something_is_missing(
    df, specs, unweighted
):
    block = compute_table(
        df, [specs["single:377"]], [], [], unweighted,
        row_categories={"single:377": ["Male", "Female"]},
    )["blocks"][0]
    assert block["hidden_categories"] == ["In another way"]
    assert "In another way" in block["all_categories"]


def test_hiding_every_row_is_refused(df, specs, unweighted):
    with pytest.raises(TableSpecError, match="nothing to show"):
        compute_table(df, [specs["single:401"]], [], [], unweighted,
                      row_categories={"single:401": []})


def test_hiding_an_unknown_category_is_refused(df, specs, unweighted):
    with pytest.raises(TableSpecError, match="Not a category"):
        compute_table(df, [specs["single:401"]], [], [], unweighted,
                      row_categories={"single:401": ["Trust a lot"]})


def test_hiding_rows_keeps_the_questions_own_order(df, specs, unweighted):
    trust = specs["single:401"]
    block = compute_table(
        df, [trust], [], [], unweighted,
        row_categories={"single:401": ["Not at all", "Trust a great deal"]},
    )["blocks"][0]
    # Declared order wins over the order the categories were listed in.
    assert [r["label"] for r in block["rows"]] == ["Trust a great deal", "Not at all"]


# ---------------------------------------------------------------- hiding columns


def test_dropping_a_banner_column_leaves_the_other_columns_untouched(
    df, specs, unweighted
):
    """Removing a small subgroup from the banner must not restate the rest."""
    full = compute_table(
        df, [specs["single:401"]], [{"var_key": "single:377"}], [specs["single:377"]],
        unweighted,
    )
    trimmed = compute_table(
        df, [specs["single:401"]],
        [{"var_key": "single:377", "categories": ["Male", "Female"]}],
        [specs["single:377"]], unweighted,
    )
    assert [c["label"] for c in trimmed["columns"]] == ["Total", "Male", "Female"]
    # Letters close up rather than leaving a gap.
    assert [c["letter"] for c in trimmed["columns"]] == ["", "a", "b"]
    assert (trimmed["blocks"][0]["bases_unweighted"][:3]
            == full["blocks"][0]["bases_unweighted"][:3])


# ---------------------------------------------------------------- removing rows


def test_removing_a_category_rebases_the_question(df, specs, unweighted):
    """The Excel pivot default: untick an item and the records are gone, so the
    base shrinks and the remaining percentages still sum to 100%."""
    trust = specs["single:401"]
    full = compute_table(df, [trust], [], [], unweighted)["blocks"][0]
    rebased = compute_table(
        df, [trust], [], [], unweighted,
        row_exclusions={"single:401": ["Don't know"]},
    )["blocks"][0]

    assert rebased["bases_unweighted"][0] < full["bases_unweighted"][0]
    assert sum(r["cells"][0]["col_pct"] for r in rebased["rows"]) == pytest.approx(1.0)
    # Every remaining percentage goes up, since the base got smaller.
    before = {r["label"]: r["cells"][0]["col_pct"] for r in full["rows"]}
    for row in rebased["rows"]:
        assert row["cells"][0]["col_pct"] > before[row["label"]]


def test_a_removed_category_disappears_rather_than_showing_greyed(df, specs, unweighted):
    block = compute_table(
        df, [specs["single:401"]], [], [], unweighted,
        row_exclusions={"single:401": ["Don't know"]},
    )["blocks"][0]
    assert "Don't know" not in [r["label"] for r in block["rows"]]
    assert block["dropped_categories"] == ["Don't know"]
    assert block["hidden_categories"] == []


def test_removing_and_hiding_are_different_operations(df, specs, unweighted):
    """Both make the row vanish; only one moves the numbers."""
    trust = specs["single:401"]
    kept = ["Trust a great deal", "Trust a fair amount", "Not very much", "Not at all"]
    hidden = compute_table(df, [trust], [], [], unweighted,
                           row_categories={"single:401": kept})["blocks"][0]
    removed = compute_table(df, [trust], [], [], unweighted,
                            row_exclusions={"single:401": ["Don't know"]})["blocks"][0]

    assert [r["label"] for r in hidden["rows"]] == [r["label"] for r in removed["rows"]]
    assert hidden["bases_unweighted"][0] > removed["bases_unweighted"][0]
    assert sum(r["cells"][0]["col_pct"] for r in hidden["rows"]) < 1.0
    assert sum(r["cells"][0]["col_pct"] for r in removed["rows"]) == pytest.approx(1.0)


def test_removing_a_row_category_does_not_affect_other_row_blocks(df, specs, unweighted):
    """Survey convention, and a deliberate divergence from a pivot: each question
    keeps its own base, so excluding a category of one question must not drop
    those respondents from another."""
    table = compute_table(
        df, [specs["single:401"], specs["single:377"]], [], [], unweighted,
        row_exclusions={"single:401": ["Don't know"]},
    )
    plain = compute_table(df, [specs["single:377"]], [], [], unweighted)["blocks"][0]
    assert table["blocks"][1]["bases_unweighted"] == plain["bases_unweighted"]


def test_removing_a_row_category_does_not_redefine_it_as_a_banner(df, specs, unweighted):
    """The same variable used down the side and across the top must not inherit
    the row block's exclusions."""
    table = compute_table(
        df, [specs["single:377"]], [{"var_key": "single:377"}], [specs["single:377"]],
        unweighted, row_exclusions={"single:377": ["In another way"]},
    )
    assert [c["label"] for c in table["columns"]] == [
        "Total", "Male", "Female", "In another way",
    ]
    assert [r["label"] for r in table["blocks"][0]["rows"]] == ["Male", "Female"]


def test_removing_every_category_is_refused(df, specs, unweighted):
    trust = specs["single:401"]
    with pytest.raises(TableSpecError, match="nothing to show"):
        compute_table(df, [trust], [], [], unweighted,
                      row_exclusions={"single:401": list(trust.value_labels)})


def test_removing_an_unknown_category_is_refused(df, specs, unweighted):
    with pytest.raises(TableSpecError, match="Not a category"):
        compute_table(df, [specs["single:401"]], [], [], unweighted,
                      row_exclusions={"single:401": ["Trust a lot"]})


def test_removing_a_category_also_rebases_every_banner_column(df, specs, unweighted):
    table = compute_table(
        df, [specs["single:401"]], [{"var_key": "single:377"}], [specs["single:377"]],
        unweighted, row_exclusions={"single:401": ["Don't know"]},
    )
    block = table["blocks"][0]
    for index in range(len(table["columns"])):
        assert sum(r["cells"][index]["col_pct"] for r in block["rows"]) == pytest.approx(1.0)


def test_removing_works_on_a_multi_punch_question(df, specs, unweighted):
    """A respondent who only picked the removed option leaves the base entirely."""
    religion = specs["multi:163"]
    full = compute_table(df, [religion], [], [], unweighted)["blocks"][0]
    trimmed = compute_table(df, [religion], [], [], unweighted,
                            row_exclusions={"multi:163": ["Buddhism"]})["blocks"][0]
    assert trimmed["bases_unweighted"][0] < full["bases_unweighted"][0]
    assert "Buddhism" not in [r["label"] for r in trimmed["rows"]]
