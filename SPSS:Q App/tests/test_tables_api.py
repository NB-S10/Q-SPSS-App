"""The /api/tables/compute endpoint."""
from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app

FIXTURE = "tests/fixtures/synthetic_survey.csv"


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def _upload(client, content: bytes | None = None) -> int:
    pid = client.post("/api/projects", json={"name": "T"}).json()["id"]
    if content is None:
        with open(FIXTURE, "rb") as fh:
            content = fh.read()
    return client.post(
        "/api/datasets/upload",
        data={"project_id": pid},
        files={"file": ("s.csv", content, "text/csv")},
    ).json()["id"]


@pytest.fixture
def dataset_id(client):
    return _upload(client)


def test_basic_table(client, dataset_id):
    res = client.post("/api/tables/compute", json={
        "dataset_id": dataset_id,
        "rows": ["single:401"],
        "banner": [{"var_key": "single:377"}],
    })
    assert res.status_code == 200, res.text
    table = res.json()
    assert [c["label"] for c in table["columns"]] == ["Total", "Male", "Female", "In another way"]
    assert len(table["blocks"]) == 1
    assert table["blocks"][0]["rows"]


def test_uses_the_files_weight_by_default(client, dataset_id):
    table = client.post("/api/tables/compute", json={
        "dataset_id": dataset_id, "rows": ["single:401"],
    }).json()
    assert table["weight"]["mode"] == "column"
    assert table["weight"]["column"] == "weight_demog"
    assert table["notices"] == []
    block = table["blocks"][0]
    assert block["bases_weighted"][0] != block["bases_unweighted"][0]


def test_unweighted_can_be_asked_for(client, dataset_id):
    table = client.post("/api/tables/compute", json={
        "dataset_id": dataset_id, "rows": ["single:401"], "weight_mode": "unweighted",
    }).json()
    block = table["blocks"][0]
    assert block["bases_weighted"][0] == block["bases_unweighted"][0]


def test_falling_back_to_unweighted_is_announced_not_silent(client):
    """A table that quietly comes back unweighted when weighting was asked for
    is how wrong figures get published."""
    df = pd.read_csv(FIXTURE).drop(columns=["weight_demog"])
    dataset_id = _upload(client, df.to_csv(index=False).encode())
    table = client.post("/api/tables/compute", json={
        "dataset_id": dataset_id, "rows": ["single:401"], "weight_mode": "column",
    }).json()
    assert table["weight"]["mode"] == "unweighted"
    assert table["weight"]["requested_mode"] == "column"
    assert any("no weight column" in n for n in table["notices"])


def test_several_row_variables_share_one_banner(client, dataset_id):
    table = client.post("/api/tables/compute", json={
        "dataset_id": dataset_id,
        "rows": ["single:401", "multi:163"],
        "banner": [{"var_key": "single:377"}],
    }).json()
    assert len(table["blocks"]) == 2
    assert table["blocks"][1]["is_multi"]


def test_filter_is_applied(client, dataset_id):
    table = client.post("/api/tables/compute", json={
        "dataset_id": dataset_id,
        "rows": ["single:401"],
        "filters": [{"var_key": "single:377", "categories": ["Female"]}],
    }).json()
    assert table["n_filtered"] < table["n_total"]
    assert table["filter"]


def test_unknown_row_variable_is_a_422_with_a_readable_message(client, dataset_id):
    res = client.post("/api/tables/compute", json={
        "dataset_id": dataset_id, "rows": ["single:999"],
    })
    assert res.status_code == 422
    assert "single:999" in res.json()["detail"]


def test_mistyped_filter_category_is_a_422(client, dataset_id):
    res = client.post("/api/tables/compute", json={
        "dataset_id": dataset_id,
        "rows": ["single:401"],
        "filters": [{"var_key": "single:377", "categories": ["Femail"]}],
    })
    assert res.status_code == 422
    assert "Not a category" in res.json()["detail"]


def test_missing_dataset_404s(client):
    res = client.post("/api/tables/compute", json={"dataset_id": 999999, "rows": ["x"]})
    assert res.status_code == 404


def test_base_rule_reaches_the_engine(client, dataset_id):
    ds = client.get(f"/api/datasets/{dataset_id}").json()
    trust = next(v for v in ds["variables"] if v["var_key"] == "single:401")
    client.patch(f"/api/variables/{trust['id']}", json={"missing_codes": ["Don't know"]})

    valid = client.post("/api/tables/compute", json={
        "dataset_id": dataset_id, "rows": ["single:401"], "base_rule": "valid",
    }).json()["blocks"][0]
    total = client.post("/api/tables/compute", json={
        "dataset_id": dataset_id, "rows": ["single:401"], "base_rule": "total",
    }).json()["blocks"][0]
    assert valid["bases_unweighted"][0] < total["bases_unweighted"][0]


def test_row_categories_reach_the_engine(client, dataset_id):
    full = client.post("/api/tables/compute", json={
        "dataset_id": dataset_id, "rows": ["single:377"],
    }).json()["blocks"][0]
    assert len(full["rows"]) == 3

    trimmed = client.post("/api/tables/compute", json={
        "dataset_id": dataset_id, "rows": ["single:377"],
        "row_categories": {"single:377": ["Male", "Female"]},
    }).json()["blocks"][0]
    assert [r["label"] for r in trimmed["rows"]] == ["Male", "Female"]
    assert trimmed["hidden_categories"] == ["In another way"]
    # Same base: hiding a row is presentation, not arithmetic.
    assert trimmed["bases_unweighted"] == full["bases_unweighted"]


def test_hiding_every_row_is_a_422(client, dataset_id):
    res = client.post("/api/tables/compute", json={
        "dataset_id": dataset_id, "rows": ["single:377"],
        "row_categories": {"single:377": []},
    })
    assert res.status_code == 422
    assert "nothing to show" in res.json()["detail"]


def test_banner_categories_can_be_narrowed(client, dataset_id):
    table = client.post("/api/tables/compute", json={
        "dataset_id": dataset_id, "rows": ["single:401"],
        "banner": [{"var_key": "single:377", "categories": ["Male", "Female"]}],
    }).json()
    assert [c["label"] for c in table["columns"]] == ["Total", "Male", "Female"]


def test_row_exclusions_rebase_through_the_api(client, dataset_id):
    full = client.post("/api/tables/compute", json={
        "dataset_id": dataset_id, "rows": ["single:401"],
    }).json()["blocks"][0]
    rebased = client.post("/api/tables/compute", json={
        "dataset_id": dataset_id, "rows": ["single:401"],
        "row_exclusions": {"single:401": ["Don't know"]},
    }).json()["blocks"][0]

    assert rebased["bases_unweighted"][0] < full["bases_unweighted"][0]
    assert rebased["dropped_categories"] == ["Don't know"]
    assert sum(r["cells"][0]["col_pct"] for r in rebased["rows"]) == pytest.approx(1.0)


def test_removing_every_category_is_a_422(client, dataset_id):
    ds = client.get(f"/api/datasets/{dataset_id}").json()
    trust = next(v for v in ds["variables"] if v["var_key"] == "single:401")
    res = client.post("/api/tables/compute", json={
        "dataset_id": dataset_id, "rows": ["single:401"],
        "row_exclusions": {"single:401": list(trust["value_labels"])},
    })
    assert res.status_code == 422
    assert "nothing to show" in res.json()["detail"]
