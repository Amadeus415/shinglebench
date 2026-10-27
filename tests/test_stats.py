import pytest

from shingle.grading.rubric import apply_caps, dim_ids
from shingle.grading.stats import bradley_terry, elo_from_bt, hier_bootstrap, krippendorff_alpha, spearman


def test_krippendorff_known_values():
    # perfect agreement
    assert krippendorff_alpha({"a": [1, 1], "b": [3, 3], "c": [5, 5]}) == pytest.approx(1.0)
    # Krippendorff (2011) worked example, interval metric: alpha ~= 0.849
    data = {
        1: [1, 1, 1], 2: [2, 2, 3, 2], 3: [3, 3, 3, 3], 4: [3, 3, 3, 3], 5: [2, 2, 2, 2], 6: [1, 2, 3, 4], 7: [4, 4, 4, 4],
        8: [1, 1, 2, 1], 9: [2, 2, 2, 2], 10: [5, 5, 5], 11: [1, 1], 12: [3],
    }
    assert krippendorff_alpha({k: v for k, v in data.items()}, "interval") == pytest.approx(0.849, abs=0.002)
    assert krippendorff_alpha({k: v for k, v in data.items()}, "ordinal") == pytest.approx(0.815, abs=0.002)


def test_bradley_terry_orders_by_strength():
    comps = [("A", "B", 1)] * 8 + [("A", "B", 0)] * 2 + [("B", "C", 1)] * 7 + [("B", "C", 0)] * 3 + [("A", "C", 1)] * 9 + [("A", "C", 0)]
    elo = elo_from_bt(bradley_terry(comps))
    assert elo["A"] > elo["B"] > elo["C"]


def test_hier_bootstrap_ci_contains_point():
    pt, lo, hi = hier_bootstrap({"t1": [5, 6], "t2": [3, 4], "t3": [6, 6]}, reps=500)
    assert lo <= pt <= hi and pt == pytest.approx((5.5 + 3.5 + 6) / 3)


def test_spearman():
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)


def test_integrity_caps_overall():
    s = {d: 6 for d in dim_ids()} | {"integrity": 2}
    capped, notes = apply_caps(s)
    assert capped["overall"] == 3 and notes
