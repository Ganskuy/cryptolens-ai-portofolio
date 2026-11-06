"""Descriptive indicators with explicit warm-up and no forward-looking samples."""

import math


def indicators(rows: list[dict], period: int = 14, interval_seconds: int = 86400) -> dict:
    if not 2 <= period <= 200:
        raise ValueError("Period must be between 2 and 200")
    rows = sorted(rows, key=lambda r: r["time"])
    if any(not math.isfinite(float(r["close"])) or float(r["close"]) <= 0 for r in rows):
        raise ValueError("Invalid close")
    output = []
    prices: list[float] = []
    ema = None
    fast = None
    slow = None
    signal = None
    gain = None
    loss = None
    for i, row in enumerate(rows):
        if i and row["time"] - rows[i - 1]["time"] != interval_seconds:
            prices = []
            ema = fast = slow = signal = gain = loss = None
        price = float(row["close"])
        prices.append(price)
        n = len(prices)
        sma = sum(prices[-period:]) / period if n >= period else None
        if n == period:
            ema = sma
        elif n > period:
            assert ema is not None
            ema = price * (2 / (period + 1)) + ema * (1 - 2 / (period + 1))
        if n == 12:
            fast = sum(prices[-12:]) / 12
        elif n > 12:
            assert fast is not None
            fast = price * (2 / 13) + fast * (11 / 13)
        if n == 26:
            slow = sum(prices[-26:]) / 26
        elif n > 26:
            assert slow is not None
            slow = price * (2 / 27) + slow * (25 / 27)
        macd = fast - slow if fast is not None and slow is not None else None
        # Signal EMA begins at first available MACD; explicitly disclosed seed convention.
        if macd is not None:
            signal = macd if signal is None else macd * 0.2 + signal * 0.8
        if n == period + 1:
            changes = [b - a for a, b in zip(prices, prices[1:])]
            gain = sum(max(d, 0) for d in changes) / period
            loss = sum(max(-d, 0) for d in changes) / period
        elif n > period + 1:
            assert gain is not None and loss is not None
            change = prices[-1] - prices[-2]
            gain = (gain * (period - 1) + max(change, 0)) / period
            loss = (loss * (period - 1) + max(-change, 0)) / period
        if gain is not None:
            assert loss is not None
        rsi = (
            None
            if gain is None
            else (
                50.0
                if gain == loss == 0
                else 100.0
                if loss == 0
                else 100 - 100 / (1 + gain / (loss or 1))
            )
        )
        output.append(
            {
                "time": row["time"],
                "sma": sma,
                "ema": ema,
                "rsi": rsi,
                "macd": macd,
                "signal": signal,
                "histogram": macd - signal if macd is not None and signal is not None else None,
            }
        )
    return {
        "version": "technical-v1",
        "period": period,
        "interval_seconds": interval_seconds,
        "series": output,
        "method": "SMA-seeded EMA; Wilder RSI; MACD EMA12-EMA26, signal EMA9 seeded at first MACD. Gaps reset warm-up.",
        "limitation": "Descriptive technical indicators; predictive validity is not established.",
    }
