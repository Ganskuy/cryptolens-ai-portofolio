import math

import numpy as np
import pytest

from app.analytics import correlation, metrics


def rows(prices):
    return [{"time": i * 86400, "close": p} for i, p in enumerate(prices)]


def test_returns_independent_expected():
    m = metrics(rows([100, 110, 99, 108.9]), 3)
    assert m["simple_returns"] == pytest.approx([0.1, -0.1, 0.1])
    assert m["cumulative_return"] == pytest.approx(0.089)
    assert m["daily_volatility"] == pytest.approx(math.sqrt(0.04 / 3))
    assert m["max_drawdown"] == pytest.approx(-0.1)
    assert m["annualized_volatility"] is None
    assert m["var_95"] == pytest.approx(0.08)
    assert m["cvar_95"] == pytest.approx(0.1)


def test_zero_denominators():
    m = metrics(rows([100] * 91), 90, 0)
    assert m["sharpe"] is None and m["sortino"] is None
    assert m["annualized_volatility"] == 0


def test_missing_rf_not_assumed_zero():
    m = metrics(rows([100 + i + math.sin(i) for i in range(91)]), 90)
    assert m["eligible"] and m["sharpe"] is None


def test_missing_candles_never_bridged():
    data = rows([100 + i for i in range(91)])
    del data[20:30]
    m = metrics(data, 90)
    assert len(m["simple_returns"]) == 79
    assert not m["eligible"]


@pytest.mark.parametrize("prices", [[100, 0], [100, -1], [100, float("nan")], [100, float("inf")]])
def test_invalid_prices(prices):
    with pytest.raises(ValueError):
        metrics(rows(prices), 30)


def test_duplicates_rejected():
    with pytest.raises(ValueError):
        metrics([{"time": 0, "close": 1}, {"time": 0, "close": 2}], 30)


def test_empty_and_single():
    assert not metrics([], 90)["eligible"]
    assert not metrics(rows([100]), 90)["eligible"]


def test_correlation_alignment():
    a = rows([100 + i + math.sin(i) for i in range(91)])
    result = correlation({"a": a, "b": a[5:]})
    assert result["observations"] == 85
    assert result["matrix"][0][1] == pytest.approx(1)


def test_annualization_and_ratio():
    prices = [100]
    returns = [0.01, -0.02, 0.03] * 30
    for r in returns:
        prices.append(prices[-1] * (1 + r))
    m = metrics(rows(prices), 90, 0)
    expected = np.std(returns, ddof=1) * math.sqrt(365)
    assert m["annualized_volatility"] == pytest.approx(expected)
    assert m["sharpe"] == pytest.approx(np.mean(returns) / np.std(returns, ddof=1) * math.sqrt(365))
    assert len(m["rolling"]) == 61
