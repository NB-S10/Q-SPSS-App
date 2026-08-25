"""Weight resolution. Most files arrive already weighted, so this is mostly
about using an existing column correctly rather than computing one."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.core.weights import (
    classify_efficiency,
    find_weight_candidates,
    inspect_weights,
    kish_effective_base,
    resolve_weights,
    weighting_efficiency,
)
from app.main import app

FIXTURE = "tests/fixtures/synthetic_survey.csv"


def test_house_weight_column_wins_over_other_candidates():
    assert find_weight_candidates(["wt", "weight_demog", "age"])[0] == "weight_demog"


def test_no_weight_column_found():
    info = inspect_weights(pd.DataFrame({"age": [1, 2]}))
    assert not info.has_weight and info.column is None


def test_detects_the_fixture_weight():
    info = inspect_weights(pd.read_csv(FIXTURE))
    assert info.column == "weight_demog"
    assert info.n_invalid == 0
    assert not info.effectively_unweighted


def test_all_ones_is_reported_as_effectively_unweighted():
    """A weight column of all 1s means the file was exported unweighted.
    Presenting that as a weighted dataset would be misleading."""
    info = inspect_weights(pd.DataFrame({"weight_demog": [1.0] * 50}))
    assert info.effectively_unweighted
    assert any("effectively unweighted" in w for w in info.warnings)


def test_unusable_weight_column_is_rejected_not_used():
    info = inspect_weights(pd.DataFrame({"weight_demog": ["a", "b", None]}))
    assert info.column is None
    assert any("no usable values" in w for w in info.warnings)


def test_invalid_weights_are_counted_and_warned_about():
    info = inspect_weights(pd.DataFrame({"weight_demog": [1.0, 0.0, -2.0, None, 1.5]}))
    assert info.n_valid == 2
    assert info.n_invalid == 3
    assert any("excluded from weighted tables" in w for w in info.warnings)


def test_unweighted_mode_gives_every_respondent_one():
    w = resolve_weights(pd.read_csv(FIXTURE), mode="unweighted")
    assert np.all(w == 1.0)
    assert w.size == 1031


def test_resolved_weights_always_align_with_the_frame():
    """Bad weights become 0 rather than dropping rows, so the array can be
    indexed against the dataframe without an offset."""
    df = pd.DataFrame({"weight_demog": [1.0, None, -3.0, 2.0]})
    w = resolve_weights(df, "column", "weight_demog")
    assert w.size == len(df)
    assert list(w) == [1.0, 0.0, 0.0, 2.0]


def test_missing_column_raises_clearly():
    with pytest.raises(KeyError, match="nope"):
        resolve_weights(pd.DataFrame({"a": [1]}), "column", "nope")


def test_unknown_mode_raises():
    with pytest.raises(ValueError, match="Unknown weight mode"):
        resolve_weights(pd.DataFrame({"a": [1]}), "sideways")


def test_kish_effective_base_equals_n_when_unweighted():
    assert kish_effective_base(np.ones(500)) == pytest.approx(500.0)


def test_kish_effective_base_is_always_below_n_when_weights_vary():
    """This is the whole point: unequal weights buy representativeness at the
    cost of precision, and the effective base is what that costs."""
    w = np.array([0.5, 0.5, 2.0, 3.0, 1.0])
    assert kish_effective_base(w) < w.size


def test_kish_effective_base_of_nothing():
    assert kish_effective_base(np.array([])) == 0.0


def test_efficiency_of_equal_weights_is_100_percent():
    eff = weighting_efficiency(np.full(200, 1.3))
    assert eff["efficiency_percent"] == pytest.approx(100.0)
    assert eff["design_effect"] == pytest.approx(1.0)


def test_efficiency_bands():
    assert classify_efficiency(95) == "Excellent"
    assert classify_efficiency(85) == "Good"
    assert classify_efficiency(75) == "Acceptable"
    assert classify_efficiency(65) == "Poor"
    assert classify_efficiency(40) == "Very poor"


def test_percentiles_expose_a_single_extreme_weight():
    """One respondent on a weight of 40 barely moves the efficiency figure, so
    the spread has to be reported alongside it."""
    w = np.append(np.ones(999), 40.0)
    eff = weighting_efficiency(w)
    assert eff["max_weight"] == 40.0
    assert eff["p99"] < 2.0


class TestWeightsEndpoint:
    @pytest.fixture
    def client(self):
        with TestClient(app) as c:
            yield c

    def _upload(self, client, content: bytes, name="s.csv"):
        pid = client.post("/api/projects", json={"name": "W"}).json()["id"]
        return client.post(
            "/api/datasets/upload",
            data={"project_id": pid},
            files={"file": (name, content, "text/csv")},
        ).json()

    def test_reports_an_existing_weight(self, client):
        with open(FIXTURE, "rb") as fh:
            info = self._upload(client, fh.read())
        res = client.get(f"/api/datasets/{info['id']}/weights").json()
        assert res["has_weight"]
        assert res["weight_column"] == "weight_demog"
        assert res["band"] in {"Excellent", "Good", "Acceptable", "Poor", "Very poor"}
        assert res["diagnostics"]["effective_base"] < res["n_rows"]

    def test_reports_no_weight_when_the_column_is_absent(self, client):
        df = pd.read_csv(FIXTURE).drop(columns=["weight_demog"])
        info = self._upload(client, df.to_csv(index=False).encode())
        res = client.get(f"/api/datasets/{info['id']}/weights").json()
        assert not res["has_weight"]
        assert res["diagnostics"] is None

    def test_weight_column_recorded_on_the_dataset(self, client):
        with open(FIXTURE, "rb") as fh:
            info = self._upload(client, fh.read())
        assert client.get(f"/api/datasets/{info['id']}").json()["weight_column"] == "weight_demog"

    def test_missing_dataset_404s(self, client):
        assert client.get("/api/datasets/999999/weights").status_code == 404
