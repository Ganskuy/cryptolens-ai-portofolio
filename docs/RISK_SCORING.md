# Risk scoring — rank-v2

Universe: explicit supported assets minus stablecoins, data-ineligible assets, stale live candle series and assets below a requested reported USD volume threshold. Exclusion reasons are returned. Period is 30–1826 days. Weight w is between zero and one.

For eligible assets, independently min-max normalize annualized volatility and absolute maximum drawdown over the same eligible universe. A constant metric receives normalized value zero. Score = 100 * [w * volatility_normalized + (1-w) * drawdown_normalized]. Lower is lower relative historical risk under these two metrics. Ties use canonical asset ID for deterministic ordering.

Default w=0.5. Changing universe, period, filtering or weight changes interpretation. Return and liquidity are displayed/filterable but are not silently added to the balanced score. The API returns methodology version and each normalized component. Underlying datasets are hashed using asset, data, period, risk-free assumption and methodology.

USDC is excluded from the general ranking. Its separate historical stability fields describe deviations of daily USDC/USDT closes from one USDT, not a verified USD peg. Daily closes miss intraday events. No invented issuer, reserve, custody, concentration, redemption, counterparty or regulatory-risk score is provided.

This score is not expected return, suitability advice, a forward risk forecast or a claim that one asset is objectively best. Historical ranks are not backtested. There is no automated order execution.

## Additional presets

`balanced` retains the original composite. `volatility` sorts annualized volatility ascending;
`drawdown` sorts absolute maximum drawdown ascending. `liquidity` sorts negative reported USD
volume (highest volume first) and rejects stale live metadata; this is not executable order-book
depth. `sharpe` requires an explicit annual risk-free decimal and sorts negative historical Sharpe
(highest first). Missing ratios are excluded. All presets retain stablecoin/coverage/staleness
gates and deterministic asset-ID tie-breaking. Scores have preset-specific units; only balanced
scores use a 0–100 bar. The API returns the actual methodology and score-unit disclosure.
