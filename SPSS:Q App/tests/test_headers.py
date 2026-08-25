from app.core.headers import detect_header_style, parse_header


def test_metadata_column_has_no_code():
    m = parse_header("Response ID")
    assert m.is_meta and m.code == "" and m.question_text == "Response ID"


def test_single_response_header():
    m = parse_header("75: How old are you?")
    assert (m.code, m.option_text, m.question_text) == ("75", "", "How old are you?")
    assert not m.is_option


def test_option_header():
    m = parse_header("163: Buddhism:Which religions do you consider yourself part of?")
    assert m.code == "163"
    assert m.option_text == "Buddhism"
    assert m.question_text == "Which religions do you consider yourself part of?"
    assert m.is_option


def test_question_text_may_contain_its_own_colon():
    """Real matrix questions end in a colon, producing a three-colon header.
    Everything from the third part on is question text and must be rejoined."""
    m = parse_header("481: Andy Burnham:Please tell us your view of each of the following:")
    assert m.colon_count == 3
    assert m.option_text == "Andy Burnham"
    assert m.question_text == "Please tell us your view of each of the following:"


def test_letter_suffixed_codes():
    assert parse_header("12a: Do you agree?").code == "12a"


def test_specify_variants_all_detected():
    for option in ["Other (Please Specify)", "Any other background (Please describe)",
                   "Other (Please specify) (text)"]:
        assert parse_header(f"9: {option}:Question?").is_specify, option


def test_ordinary_option_is_not_specify():
    assert not parse_header("163: Christianity:Question?").is_specify


def test_header_style_detection():
    assert detect_header_style(["1: A?", "2: B?", "Response ID"]) == "alchemer"
    assert detect_header_style(["age", "gender", "region"]) == "generic"
    assert detect_header_style([]) == "generic"
