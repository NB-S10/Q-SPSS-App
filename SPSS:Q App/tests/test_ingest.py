"""Upload path: file in, variable tree out."""
from __future__ import annotations

import io

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.core.ingest import IngestError, read_upload, summarise
from app.main import app

FIXTURE = "tests/fixtures/synthetic_survey.csv"


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def project(client):
    return client.post("/api/projects", json={"name": "Ingest test"}).json()["id"]


def _fixture_bytes() -> bytes:
    with open(FIXTURE, "rb") as fh:
        return fh.read()


def test_rejects_unsupported_extension():
    with pytest.raises(IngestError, match="Upload a .csv"):
        read_upload("data.sav", b"")


def test_rejects_duplicate_headers():
    csv = b"age,age\n1,2\n"
    with pytest.raises(IngestError, match="share the same header"):
        read_upload("dupes.csv", csv)


def test_strips_whitespace_from_headers_and_values():
    df = read_upload("x.csv", b"  a ,b\n  yes  ,1\n")
    assert list(df.columns) == ["a", "b"]
    assert df["a"].iloc[0] == "yes"


def test_summarise_collapses_columns_into_questions():
    df = pd.read_csv(FIXTURE)
    info = summarise(df)
    assert info["header_style"] == "alchemer"
    assert info["n_columns"] == 20
    # Multi-punch and matrix questions each cover several columns, so there are
    # fewer questions than columns.
    assert info["n_questions"] < info["n_columns"]
    assert info["by_kind"]["multi"] == 2


def test_multi_punch_options_are_offered_individually_as_well():
    """A combined table for the whole question, plus one variable per option so
    a single option can be tabulated or used as a column."""
    info = summarise(pd.read_csv(FIXTURE))
    assert info["by_kind"]["multi_item"] == 4


def test_flags_the_routed_empty_question():
    info = summarise(pd.read_csv(FIXTURE))
    assert any("routed" in n.lower() for f in info["flagged"] for n in f["notes"])


def test_upload_round_trip(client, project):
    res = client.post(
        "/api/datasets/upload",
        data={"project_id": project, "name": "Wave 1"},
        files={"file": ("synthetic_survey.csv", _fixture_bytes(), "text/csv")},
    )
    assert res.status_code == 201, res.text
    info = res.json()
    assert info["n_rows"] == 1031

    ds = client.get(f"/api/datasets/{info['id']}").json()
    by_key = {v["var_key"]: v for v in ds["variables"]}
    assert by_key["multi:163"]["n_columns"] == 4
    assert by_key["single:29"]["kind"] == "single"
    assert by_key["matrix_item:481:Andy Burnham"]["parent_key"] == "matrix:481"
    assert by_key["multi:595"]["notes"]


def test_upload_to_missing_project_404s(client):
    res = client.post(
        "/api/datasets/upload",
        data={"project_id": 999999},
        files={"file": ("x.csv", b"a\n1\n", "text/csv")},
    )
    assert res.status_code == 404


def test_bad_file_gives_a_readable_error(client, project):
    res = client.post(
        "/api/datasets/upload",
        data={"project_id": project},
        files={"file": ("notes.txt", b"hello", "text/plain")},
    )
    assert res.status_code == 422
    assert ".csv" in res.json()["detail"]


def test_rows_endpoint_windows_the_data(client, project):
    info = client.post(
        "/api/datasets/upload",
        data={"project_id": project},
        files={"file": ("s.csv", _fixture_bytes(), "text/csv")},
    ).json()
    page = client.get(f"/api/datasets/{info['id']}/rows?offset=10&limit=5").json()
    assert len(page["rows"]) == 5
    assert page["total"] == 1031
