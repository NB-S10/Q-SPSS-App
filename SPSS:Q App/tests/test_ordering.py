"""Category ordering. Alchemer gives no answer order, so this is inferred where
it safely can be and left alone where it can't."""
from __future__ import annotations

from app.core.ordering import is_non_substantive, normalise, suggest_order


def test_curly_and_straight_apostrophes_are_the_same_answer():
    """The same export contains both "Don't know" and "Don't know" with a curly
    apostrophe. Treating them as different answers would split the category."""
    assert normalise("Don’t know") == normalise("Don't know")


def test_non_substantive_detection():
    for label in ["Don't know", "Don’t know", "Prefer not to say",
                  "Don't know / can't remember", "None of the above",
                  "Not applicable", "Other (Please Specify)"]:
        assert is_non_substantive(label), label


def test_real_answers_are_not_non_substantive():
    for label in ["No religion/Atheism", "Not working and not seeking work",
                  "Very unfavourable", "No annual income"]:
        assert not is_non_substantive(label), label


def test_favourability_scale():
    values = ["Very favourable", "Slightly favourable", "Don't know",
              "Very unfavourable", "Somewhat favourable", "Somewhat unfavourable",
              "Neutral", "Slightly unfavourable"]
    order, rule = suggest_order(values)
    assert rule == "scale"
    assert order == [
        "Very favourable", "Somewhat favourable", "Slightly favourable", "Neutral",
        "Slightly unfavourable", "Somewhat unfavourable", "Very unfavourable",
        "Don't know",
    ]


def test_support_oppose_scale_with_curly_apostrophe():
    order, rule = suggest_order(
        ["Somewhat support", "Strongly oppose", "Don’t know",
         "Neither support nor oppose", "Strongly support", "Somewhat oppose"])
    assert rule == "scale"
    assert order[0] == "Strongly support"
    assert order[-1] == "Don’t know"
    assert order[-2] == "Strongly oppose"


def test_elliptical_trust_scale():
    """"How much do you trust X?" answers carry no scale word of their own --
    the stem lives in the question."""
    order, rule = suggest_order(
        ["Trust a great deal", "Not at all", "Not very much",
         "Trust a fair amount", "Don't know"])
    assert rule == "scale"
    assert order == ["Trust a great deal", "Trust a fair amount",
                     "Not very much", "Not at all", "Don't know"]


def test_not_very_is_weaker_than_not_at_all():
    """"Not very likely" contains the word "very" but is the MILDER negative.
    Scanning intensity words naively scores it as the strongest."""
    order, _ = suggest_order(
        ["Very likely", "Not at all likely", "Fairly likely", "Not very likely"])
    assert order == ["Very likely", "Fairly likely", "Not very likely", "Not at all likely"]


def test_zero_to_ten_scale_sorts_numerically():
    order, rule = suggest_order(
        ["10 - certain to vote", "7", "Don't know", "0 - certain not to vote", "5"])
    assert rule == "numeric"
    assert order == ["0 - certain not to vote", "5", "7", "10 - certain to vote", "Don't know"]


def test_age_bands():
    order, rule = suggest_order(["65+", "18-24", "45-54", "25-34", "35-44", "55-64"])
    assert rule == "numeric"
    assert order == ["18-24", "25-34", "35-44", "45-54", "55-64", "65+"]


def test_income_bands_ignore_currency_symbols_and_separators():
    order, rule = suggest_order(
        ["£100,000 or more", "£90,000 - £99,999", "No annual income",
         "£10,000 - £14,999", "Less than £10,000", "Prefer not to say"])
    assert rule == "numeric"
    assert order == ["No annual income", "Less than £10,000", "£10,000 - £14,999",
                     "£90,000 - £99,999", "£100,000 or more", "Prefer not to say"]


def test_nominal_categories_keep_data_order_but_sink_dont_knows():
    """Silently reordering regions or parties would be worse than leaving them.
    The one safe move is pushing non-substantive answers to the bottom."""
    order, rule = suggest_order(
        ["London", "Prefer not to say", "South East", "Scotland"])
    assert rule == "data"
    assert order == ["London", "South East", "Scotland", "Prefer not to say"]


def test_empty_input():
    assert suggest_order([]) == ([], "data")


def test_order_is_a_permutation_of_the_input():
    values = ["Very favourable", "Neutral", "Don't know", "Very unfavourable"]
    order, _ = suggest_order(values)
    assert sorted(order) == sorted(values)
