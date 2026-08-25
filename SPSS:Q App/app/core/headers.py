"""Alchemer header parsing.

Alchemer exports encode a question's structure in the column header, using the
colon count:

    0 colons   metadata / derived column      "Response ID", "weight_demog"
    1 colon    CODE: QUESTION                 single response
    2+ colons  CODE: OPTION: QUESTION         multi-punch option or matrix item

Two details that only show up in real exports:

* The question text itself often ends in a colon ("...each of the following:"),
  so a header can have three colons and still be a plain option. Everything from
  the third part onward is question text, rejoined.
* "Other (Please specify)" follow-ups are free-text columns sitting inside an
  otherwise categorical group. They must be split off before the group is
  classified, or a clean multi-punch question looks like a matrix.

Ported from Apps/Regression App/Regression App/app.js:65-79 (parseHeaderMeta),
with the specify handling added.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# Question codes are digits with an optional letter suffix: "12", "12a".
CODE_RE = re.compile(r"^(\d+[a-z]?):")

# "(Please specify)", "(please describe)", "(text)" -- the free-text follow-ups.
SPECIFY_RE = re.compile(r"\(\s*(?:please\s+(?:specify|describe)|text)\s*\)", re.I)


@dataclass(frozen=True)
class HeaderMeta:
    raw: str
    code: str
    option_text: str
    question_text: str
    colon_count: int
    is_specify: bool

    @property
    def is_meta(self) -> bool:
        """No question code means it isn't survey response data -- an ID, a
        timestamp, a weight, or a derived column someone added by hand."""
        return not self.code

    @property
    def is_option(self) -> bool:
        return bool(self.code) and self.colon_count >= 2


def parse_header(raw: str) -> HeaderMeta:
    text = str(raw)
    parts = [p.strip() for p in text.split(":")]
    colon_count = len(parts) - 1

    match = CODE_RE.match(text)
    if not match:
        return HeaderMeta(text, "", "", text.strip(), colon_count, False)

    code = match.group(1)

    if colon_count == 1:
        return HeaderMeta(text, code, "", parts[1], colon_count, False)

    option_text = parts[1]
    # Rejoin the tail: question text frequently contains its own colon.
    question_text = ": ".join(parts[2:]).strip()
    return HeaderMeta(
        text,
        code,
        option_text,
        question_text,
        colon_count,
        bool(SPECIFY_RE.search(option_text)),
    )


def detect_header_style(columns: list[str]) -> str:
    """"alchemer" when enough headers carry a question code to trust the
    contract, otherwise "generic" and the user declares structure by hand."""
    if not columns:
        return "generic"
    coded = sum(1 for c in columns if CODE_RE.match(str(c)))
    return "alchemer" if coded / len(columns) >= 0.5 else "generic"
