"""statman/stats.py: Pearson-r og den regulariserte ufullstendige betafunksjonen."""

from __future__ import annotations

import pytest

from statman import stats


def test_pearson_is_plus_one_for_a_perfect_line() -> None:
    assert stats.pearson([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)


def test_pearson_is_minus_one_for_a_perfect_inverse_line() -> None:
    assert stats.pearson([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)


def test_pearson_is_zero_for_no_linear_relationship() -> None:
    assert stats.pearson([1, 2, 3, 4], [10, 20, 20, 10]) == pytest.approx(0.0, abs=1e-9)


def test_p_value_is_one_when_there_is_no_correlation_at_all() -> None:
    assert stats.t_test_p(0.0, 20) == pytest.approx(1.0, abs=1e-9)


def test_p_value_is_near_zero_for_a_strong_correlation_with_enough_points() -> None:
    assert stats.t_test_p(0.9, 30) < 0.001


def test_p_value_matches_a_known_reference_value() -> None:
    """r = 0,5 med n = 20 (df = 18) gir t ≈ 2,472, p (tosidig) ≈ 0,0234."""
    assert stats.t_test_p(0.5, 20) == pytest.approx(0.0234, abs=2e-3)


def test_p_value_is_zero_for_a_perfect_correlation() -> None:
    assert stats.t_test_p(1.0, 5) == 0.0
    assert stats.t_test_p(-1.0, 5) == 0.0


def test_p_value_is_one_with_too_few_points_to_test() -> None:
    """Under tre punkter er en korrelasjon udefinert som noe å teste."""
    assert stats.t_test_p(0.9, 2) == 1.0
