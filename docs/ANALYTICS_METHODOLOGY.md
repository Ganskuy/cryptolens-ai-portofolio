# Analytics methodology — daily-risk-v1

Prices are finalized daily closes at UTC boundaries. Binance quote currency is USDT. Let p[t] be the close and r[t] = p[t]/p[t-1] - 1, only when timestamps are exactly one day apart. Log returns are ln(1+r[t]). No missing candle is synthesized. Cumulative return is p[end]/p[start]-1 and describes endpoints even if interior observations are missing; coverage accompanies it.

Daily volatility is sample standard deviation (ddof=1). Annualized volatility multiplies by sqrt(365), reflecting continuous crypto trading. Rolling volatility and rolling period return use thirty contiguous daily return intervals. Annualized metrics and rankings require at least thirty returns and 95% requested-window coverage. This is a minimum data gate, not evidence of statistical stability.

Drawdown[t] = p[t]/max(p[0:t])-1. Maximum drawdown is the minimum observed drawdown, a nonpositive decimal; it may understate intraday or gap-hidden loss. Historical VaR at 95% confidence is minus the linearly interpolated 5th percentile of daily returns. CVaR is minus the mean of returns at/below that quantile. Signed VaR/CVaR can be negative if every relevant observation is a gain; this is disclosed rather than silently clipped.

For an explicitly supplied annual risk-free assumption Rf, daily rf = (1+Rf)^(1/365)-1. Sharpe = mean(r-rf)/sample_std(r)*sqrt(365). Downside deviation = sqrt(mean(min(r-rf,0)^2)), including zero shortfalls over the full sample. Sortino divides mean excess return by this downside deviation and multiplies by sqrt(365). Zero or near-zero denominators return null. Without Rf, Sharpe/Sortino remain null; downside deviation uses zero as a descriptive target, explicitly not an inferred risk-free rate.

Correlation aligns the intersection of timestamps for valid contiguous daily returns and requires thirty common observations plus nonzero variance. No forward filling. Relative performance is endpoint cumulative return for each disclosed window. Historical ranking is only at the current dataset end; there is no backtest or prediction claim.

Liquidity: CoinGecko reported volume/market cap is a turnover proxy, not executable liquidity. Binance spread = (ask-bid)/midpoint*10,000 in basis points. Supply ratio = circulating/max supply only when maximum is known and positive. Chain TVL is not token market cap and is not combined into a token valuation ratio without an explicit defensible mapping.

Independent synthetic example: prices [100,110,99,108.9] yield returns [0.1,-0.1,0.1], endpoint return 0.089, maximum drawdown -0.1, sample daily volatility sqrt(0.04/3), VaR 0.08 and CVaR 0.1. Annualized outputs are null for this short sample. These expectations are asserted in tests.

## Hourly and descriptive technical observations — technical-v1

Hourly returns require adjacent finalized timestamps exactly 3,600 seconds apart. Coverage is
contiguous intervals divided by requested hours. Daily sqrt(365) scaling is never applied to
hourly observations. The API discloses interval and source separately.

SMA uses the trailing period closes. EMA starts at the period SMA and then uses alpha=2/(N+1).
Wilder RSI seeds average gains/losses over N changes and smooths with alpha=1/N; flat series
returns 50 and zero-loss rising series returns 100. MACD is EMA12 minus EMA26; its EMA9 signal
starts at the first available MACD. Warm-up values are null. A timestamp gap resets every
warm-up state. Prefix-invariance tests check that later prices cannot change earlier values.
These are descriptive indicators; no prediction quality or trading profitability is asserted.

Aave's explicitly reviewed protocol/token mapping permits a TVL / governance-token market-cap
ratio only with both observations younger than two hours and a positive denominator. The ratio
is a descriptive cross-dataset comparison; TVL is not revenue, reserves or token-holder equity.
