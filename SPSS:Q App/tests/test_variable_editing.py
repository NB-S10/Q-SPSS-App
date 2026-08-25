"""The order-editing endpoints the Variables screen talks to."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

FIXTURE = "tests/fixtures/synthetic_survey.csv"


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def dataset(client):
    pid = client.post("/api/projects", json={"name": "Order test"}).json()["id"]
    with open(FIXTURE, "rb") as fh:
        info = client.post(
            "/api/datasets/upload",
            data={"project_id": pid},
            files={"file": ("s.csv", fh.read(), "text/csv")},
        ).json()
    return client.get(f"/api/datasets/{info['id']}").json()


def _var(dataset, key):
    return next(v for v in dataset["variables"] if v["var_key"] == key)


def test_scale_is_ordered_on_import(dataset):
    trust = _var(dataset, "single:401")
    assert trust["order_rule"] == "scale"
    assert trust["category_order"][0] == "Trust a great deal"
    assert trust["category_order"][-1] == "Don't know"


def test_nominal_variable_is_left_as_data_order(dataset):
    assert _var(dataset, "single:378")["order_rule"] == "data"


def test_saving_an_order_marks_it_as_the_users(client, dataset):
    region = _var(dataset, "single:378")
    reversed_order = list(reversed(region["category_order"]))
    res = client.patch(
        f"/api/variables/{region['id']}/order",
        json={"category_order": reversed_order},
    )
    assert res.status_code == 200
    assert res.json()["order_rule"] == "user"
    assert res.json()["category_order"] == reversed_order


def test_partial_order_is_rejected(client, dataset):
    """Accepting a short list would silently drop categories from every table
    built afterwards."""
    region = _var(dataset, "single:378")
    res = client.patch(
        f"/api/variables/{region['id']}/order",
        json={"category_order": region["category_order"][:2]},
    )
    assert res.status_code == 422
    assert "Missing" in res.json()["detail"]


def test_unknown_category_is_rejected(client, dataset):
    region = _var(dataset, "single:378")
    res = client.patch(
        f"/api/variables/{region['id']}/order",
        json={"category_order": [*region["category_order"], "Narnia"]},
    )
    assert res.status_code == 422
    assert "Not a category" in res.json()["detail"]


def test_duplicate_category_is_rejected(client, dataset):
    region = _var(dataset, "single:378")
    dupes = [region["category_order"][0], *region["category_order"]]
    res = client.patch(
        f"/api/variables/{region['id']}/order", json={"category_order": dupes}
    )
    assert res.status_code == 422
    assert "repeats" in res.json()["detail"]


def test_resuggest_discards_a_hand_made_order(client, dataset):
    trust = _var(dataset, "single:401")
    client.patch(
        f"/api/variables/{trust['id']}/order",
        json={"category_order": list(reversed(trust["category_order"]))},
    )
    res = client.post(f"/api/variables/{trust['id']}/order/suggest")
    assert res.json()["order_rule"] == "scale"
    assert res.json()["category_order"][0] == "Trust a great deal"


def test_order_survives_a_reread(client, dataset):
    region = _var(dataset, "single:378")
    wanted = list(reversed(region["category_order"]))
    client.patch(f"/api/variables/{region['id']}/order", json={"category_order": wanted})
    again = client.get(f"/api/datasets/{dataset['id']}").json()
    assert _var(again, "single:378")["category_order"] == wanted


def test_relabelling_a_variable(client, dataset):
    v = _var(dataset, "single:401")
    res = client.patch(f"/api/variables/{v['id']}", json={"label": "Trust in government"})
    assert res.json()["label"] == "Trust in government"


def test_blank_label_rejected(client, dataset):
    v = _var(dataset, "single:401")
    assert client.patch(f"/api/variables/{v['id']}", json={"label": "  "}).status_code == 422


def test_missing_codes_must_be_real_categories(client, dataset):
    """Marking "Don't know" as a missing code excludes it from every base, so a
    typo here would quietly change every percentage."""
    v = _var(dataset, "single:401")
    assert client.patch(
        f"/api/variables/{v['id']}", json={"missing_codes": ["Dont know"]}
    ).status_code == 422
    assert client.patch(
        f"/api/variables/{v['id']}", json={"missing_codes": ["Don't know"]}
    ).status_code == 200
