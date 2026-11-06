from typing import Any

import numpy as np
import polars as pl

VERSION = "daily-risk-v1"


def metrics(
    candles: list[dict[str, Any]], days: int, risk_free: float | None = None
) -> dict[str, Any]:
    """Daily UTC observations; never bridge gaps when computing daily returns."""
    rows = sorted(candles, key=lambda r: r["time"])[-(days + 1) :]
    if len({r["time"] for r in rows}) != len(rows):
        raise ValueError("duplicate timestamps")
    if not rows:
        return {
            "eligible": False,
            "reason": "No finalized candles",
            "coverage": 0,
            "version": VERSION,
        }
    frame = pl.DataFrame(rows)
    p = frame["close"].cast(pl.Float64).to_numpy()
    t = frame["time"].to_numpy()
    if not np.isfinite(p).all() or (p <= 0).any():
        raise ValueError("invalid close prices")
    contiguous = np.diff(t) == 86400
    r = (p[1:] / p[:-1] - 1)[contiguous]
    coverage = min(1.0, len(r) / days)
    draw = p / np.maximum.accumulate(p) - 1
    base: dict[str, Any] = {
        "version": VERSION,
        "observations": len(r),
        "coverage": coverage,
        "window_start": int(t[0]),
        "window_end": int(t[-1]),
        "units": "decimal returns; annualized ratios",
        "risk_free_annual": risk_free,
        "eligible": len(r) >= 30 and coverage >= 0.95,
        "cumulative_return": float(p[-1] / p[0] - 1),
        "max_drawdown": float(draw.min()),
        "series": [
            {
                "time": int(t[i]),
                "close": float(p[i]),
                "drawdown": float(draw[i]),
                "cumulative_return": float(p[i] / p[0] - 1),
            }
            for i in range(len(p))
        ],
    }
    if len(r) < 2:
        return {**base, "eligible": False, "reason": "Insufficient contiguous daily returns"}
    sd = float(np.std(r, ddof=1))
    rf = (1 + risk_free) ** (1 / 365) - 1 if risk_free is not None else None
    excess = r - (rf or 0)
    down = float(np.sqrt(np.mean(np.minimum(excess, 0) ** 2)))
    q = float(np.quantile(r, 0.05, method="linear"))
    rolling = []
    for i in range(30, len(p)):
        rr = p[i - 29 : i + 1] / p[i - 30 : i] - 1
        if (np.diff(t[i - 30 : i + 1]) == 86400).all():
            rolling.append(
                {
                    "time": int(t[i]),
                    "volatility": float(np.std(rr, ddof=1) * np.sqrt(365)),
                    "return": float(p[i] / p[i - 30] - 1),
                }
            )
    eligible = base["eligible"]
    return {
        **base,
        "reason": None if eligible else "Requires 30 returns and 95% coverage",
        "daily_volatility": sd,
        "annualized_volatility": sd * np.sqrt(365) if eligible else None,
        "sharpe": float(np.mean(excess) / sd * np.sqrt(365))
        if eligible and rf is not None and sd > 1e-12
        else None,
        "sortino": float(np.mean(excess) / down * np.sqrt(365))
        if eligible and rf is not None and down > 1e-12
        else None,
        "downside_deviation": down,
        "var_95": -q,
        "cvar_95": -float(r[r <= q].mean()),
        "return_distribution": [
            {"lower": float(lo), "upper": float(hi), "count": int(count)}
            for count, lo, hi in zip(
                *((lambda h: (h[0], h[1][:-1], h[1][1:]))(np.histogram(r, bins=12)))
            )
        ],
        "simple_returns": r.tolist(),
        "log_returns": np.log1p(r).tolist(),
        "rolling": rolling,
    }


def correlation(datasets: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    returns = {}
    for asset, rows in datasets.items():
        rows = sorted(rows, key=lambda r: r["time"])
        returns[asset] = {
            b["time"]: float(b["close"]) / float(a["close"]) - 1
            for a, b in zip(rows, rows[1:])
            if b["time"] - a["time"] == 86400
        }
    common = sorted(set.intersection(*(set(r) for r in returns.values()))) if returns else []
    ids = list(returns)
    matrix: list[list[float | None]] = []
    for a in ids:
        line = []
        for b in ids:
            x, y = [returns[a][t] for t in common], [returns[b][t] for t in common]
            value = (
                float(np.corrcoef(x, y)[0, 1])
                if len(common) >= 30 and np.std(x) > 1e-12 and np.std(y) > 1e-12
                else None
            )
            line.append(value)
        matrix.append(line)
    rolling = []
    if len(ids) >= 2:
        for i in range(30, len(common) + 1):
            window = common[i - 30 : i]
            x, y = [returns[ids[0]][t] for t in window], [returns[ids[1]][t] for t in window]
            if np.std(x) > 1e-12 and np.std(y) > 1e-12:
                rolling.append(
                    {"time": int(window[-1]), "correlation": float(np.corrcoef(x, y)[0, 1])}
                )
    return {
        "rolling_pair": ids[:2],
        "rolling": rolling,
        "assets": ids,
        "matrix": matrix,
        "observations": len(common),
        "alignment": "intersection of contiguous daily returns",
    }
