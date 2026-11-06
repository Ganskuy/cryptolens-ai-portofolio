# Explicit identity mapping; no fuzzy ticker joins or inferred protocol/token links.
ASSETS = [
    ("bitcoin", "BTC", "Bitcoin", "BTCUSDT", False),
    ("ethereum", "ETH", "Ethereum", "ETHUSDT", False),
    ("solana", "SOL", "Solana", "SOLUSDT", False),
    ("binancecoin", "BNB", "BNB", "BNBUSDT", False),
    ("ripple", "XRP", "XRP", "XRPUSDT", False),
    ("cardano", "ADA", "Cardano", "ADAUSDT", False),
    ("dogecoin", "DOGE", "Dogecoin", "DOGEUSDT", False),
    ("chainlink", "LINK", "Chainlink", "LINKUSDT", False),
    ("avalanche-2", "AVAX", "Avalanche", "AVAXUSDT", False),
    ("usd-coin", "USDC", "USDC", "USDCUSDT", True),
]
IDS = {a[0] for a in ASSETS}
SYMBOLS = {a[3]: a[0] for a in ASSETS}
