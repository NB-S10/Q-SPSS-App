"""Suggesting a sensible category order.

Alchemer exports the response text but not the questionnaire's answer order, so
categories arrive in whatever order the first few respondents happened to pick.
A favourability scale comes back as "Very favourable, Slightly favourable,
Don't know, Very unfavourable, ...".

This module guesses an order where it safely can, and says which rule it used so
the user knows how much to trust it. Anything it can't infer keeps the data
order and is corrected by dragging. Being honest about that matters more than
guessing aggressively: silently reordering a list of political parties or
occupational groups would be worse than leaving them alone.
"""
from __future__ import annotations

import re
import unicodedata

# Answers that carry no position on a scale. These always sink to the bottom,
# whatever else happens, which is the one rule that is safe for every question.
NON_SUBSTANTIVE = (
    "dont know", "do not know", "not sure", "unsure", "cant remember",
    "cannot remember", "cant recall", "no opinion", "no view",
    "prefer not to say", "rather not say", "none of the above", "none of these",
    "not applicable", "na", "other", "other please specify", "dont mind",
    "havent heard", "never heard", "not heard of",
)

# Higher means a stronger claim. Used to sort within a polarity.
#
# Negated intensities are checked before the table, because "not very much" is a
# WEAK negative but contains the word "very" -- scanning the table first would
# score it as the strongest. "Not at all" is the opposite: no intensity word at
# all, yet the strongest negation there is.
NEGATED_INTENSITY = (
    (4, ("not at all", "never", "none at all", "no interest at all")),
    (2, ("not very", "not particularly", "not especially")),
)
INTENSITY = (
    (4, ("very", "strongly", "extremely", "great deal", "completely", "totally",
         "certain", "definitely", "always", "a lot", "much more", "much less")),
    (3, ("somewhat", "fairly", "quite", "tend to", "fair amount", "moderately",
         "mostly", "generally", "often", "more", "less")),
    (2, ("slightly", "a little", "a bit", "marginally", "occasionally")),
)

POSITIVE = ("favourable", "favorable", "agree", "support", "likely", "trust",
            "important", "satisfied", "comfortable", "acceptable", "approve",
            "confident", "good", "better", "well", "positive", "happy", "enough")
NEGATIVE = ("unfavourable", "unfavorable", "disagree", "oppose", "unlikely",
            "distrust", "unimportant", "dissatisfied", "uncomfortable",
            "unacceptable", "disapprove", "bad", "worse", "negative", "unhappy",
            "unsupportive", "poor")
NEUTRAL = ("neither", "neutral", "no difference", "about the same",
           "about right", "no change", "middle")


def normalise(text: str) -> str:
    """Fold to a comparable form. Critically this unifies curly and straight
    apostrophes -- the same export contains both "Don't know" and "Don’t know",
    which would otherwise be treated as different answers."""
    s = unicodedata.normalize("NFKD", str(text))
    s = s.replace("’", "'").replace("‘", "'")
    s = s.lower().strip()
    return re.sub(r"[^a-z0-9 ]+", "", s).strip()


def is_non_substantive(label: str) -> bool:
    n = normalise(label)
    if not n:
        return False
    # Compound answers such as "Don't know / can't remember" match on a part.
    for token in NON_SUBSTANTIVE:
        if n == token or n.startswith(token + " ") or f" {token}" in f" {n}":
            return True
    return False


# A leading currency symbol, then digits with optional thousands separators.
# Covers 0-10 scales ("7", "10 - certain to vote"), age bands ("18-24", "65+")
# and income bands ("£90,000 - £99,999", "£100,000 or more").
_NUMBER_RE = re.compile(r"^\s*[£$€]?\s*(-?\d[\d,]*(?:\.\d+)?)")

# "No annual income" and "Under £10,000" belong at the bottom of a band scale
# but carry no leading number, so they need their own floor value.
_ZERO_BAND = ("no annual income", "no income", "nothing", "none", "zero")


def _leading_number(label: str) -> float | None:
    n = normalise(label)
    if any(n.startswith(z) or n == z for z in _ZERO_BAND):
        return 0.0
    m = _NUMBER_RE.match(str(label))
    if not m:
        # "Under £10,000" / "Less than 5" sort just below their own figure.
        under = re.match(r"^\s*(?:under|below|less than)\s+[£$€]?\s*(-?\d[\d,]*)",
                         str(label), re.I)
        if under:
            return float(under.group(1).replace(",", "")) - 0.5
        return None
    return float(m.group(1).replace(",", ""))


def _intensity(n: str) -> int:
    for rank, tokens in NEGATED_INTENSITY:
        if any(t in n for t in tokens):
            return rank
    for rank, tokens in INTENSITY:
        if any(t in n for t in tokens):
            return rank
    return 3  # an unqualified "Agree" sits between "Strongly" and "Slightly"


def _polarity(n: str) -> int | None:
    """0 positive, 1 neutral, 2 negative. None when no scale word is present."""
    if any(t in n for t in NEUTRAL):
        return 1
    # Negative first: "unfavourable" contains "favourable", "disagree"
    # contains "agree".
    if any(t in n for t in NEGATIVE):
        return 2
    if any(t in n for t in POSITIVE):
        # "not at all likely" and "not very supportive" are negative despite
        # carrying a positive stem.
        if re.search(r"\bnot\b|\bnever\b", n):
            return 2
        return 0

    # Elliptical answers, where the stem lives in the question rather than the
    # answer: "How much do you trust X?" / "A great deal", "Not very much",
    # "Not at all". Very common in UK polling and it has no scale word to match.
    if re.search(r"\bnot\b|\bnever\b|\bnone\b", n):
        return 2
    if any(t in n for t in ("great deal", "fair amount", "a lot", "a fair bit")):
        return 0
    return None


def suggest_order(values: list[str]) -> tuple[list[str], str]:
    """Return (ordered values, the rule that was applied).

    Rules, in order of confidence:
      "numeric"     every substantive label starts with a number
      "scale"       every substantive label carries a scale word
      "data"        no rule fitted; original order kept
    Non-substantive answers sink to the bottom under all three.
    """
    if not values:
        return [], "data"

    substantive = [v for v in values if not is_non_substantive(v)]
    trailing = [v for v in values if is_non_substantive(v)]

    if substantive and all(_leading_number(v) is not None for v in substantive):
        ordered = sorted(substantive, key=lambda v: _leading_number(v))
        return ordered + trailing, "numeric"

    polarities = [_polarity(normalise(v)) for v in substantive]
    if substantive and all(p is not None for p in polarities):
        def key(v: str):
            n = normalise(v)
            pol = _polarity(n)
            # Strongest positive first; strongest negative last.
            return (pol, -_intensity(n) if pol == 0 else _intensity(n))

        return sorted(substantive, key=key) + trailing, "scale"

    # Nothing inferable. Keep the data order but still sink don't-knows.
    return substantive + trailing, "data"
