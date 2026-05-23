from __future__ import annotations

import numpy as np
import pytest

from mxm.moneymachine.synthetic_assets.rolling.linear_roll import LinearRoll


def test_linear_roll_raises_on_invalid_params() -> None:
    with pytest.raises(ValueError):
        LinearRoll(
            roll_start_offset=-1, roll_duration=1
        ).compute_weights_from_bdays_to_ltd(
            bdays_to_ltd=np.array([3, 2, 1], dtype=np.int64)
        )

    with pytest.raises(ValueError):
        LinearRoll(
            roll_start_offset=2, roll_duration=0
        ).compute_weights_from_bdays_to_ltd(
            bdays_to_ltd=np.array([3, 2, 1], dtype=np.int64)
        )


def test_linear_roll_rejects_duration_longer_than_offset() -> None:
    roll = LinearRoll(roll_start_offset=2, roll_duration=5)
    d = np.array([4, 3, 2, 1], dtype=np.int64)

    with pytest.raises(ValueError):
        roll.compute_weights_from_bdays_to_ltd(bdays_to_ltd=d)


def test_linear_roll_values_three_region_example() -> None:
    # Convention: first ramp day alpha=1/D, last ramp day alpha=1.
    # N1=3, D=3 => d_low=1, ramp over d=3,2,1
    # d:  5  4   3    2    1
    #     pre pre ramp ramp ramp
    # alpha:      1/3 2/3  1
    # w_cur: 1, 1, 2/3, 1/3, 0
    roll = LinearRoll(roll_start_offset=3, roll_duration=3)
    d = np.array([5, 4, 3, 2, 1], dtype=np.int64)

    w_cur, w_nxt = roll.compute_weights_from_bdays_to_ltd(bdays_to_ltd=d)

    expected_w_cur = np.array([1.0, 1.0, 2.0 / 3.0, 1.0 / 3.0, 0.0], dtype=np.float64)
    assert np.allclose(w_cur, expected_w_cur, atol=1e-12, rtol=0.0)
    assert np.allclose(w_nxt, 1.0 - expected_w_cur, atol=1e-12, rtol=0.0)


def test_linear_roll_invariants_bounds_and_complementarity() -> None:
    roll = LinearRoll(roll_start_offset=4, roll_duration=3)
    d = np.array([10, 5, 4, 3, 2, 1, 8, 1], dtype=np.int64)  # includes jumps

    w_cur, w_nxt = roll.compute_weights_from_bdays_to_ltd(bdays_to_ltd=d)

    assert np.all(w_cur >= 0.0)
    assert np.all(w_cur <= 1.0)
    assert np.all(w_nxt >= 0.0)
    assert np.all(w_nxt <= 1.0)

    assert np.allclose(w_cur + w_nxt, 1.0, atol=1e-12, rtol=0.0)
