"""
Configurable coin universe and per-universe signal weights.

Three universes:
  - large:  rank 1-50    (BTC, ETH, SOL) — slow movers, long-term holds
  - mid:    rank 51-200  (PEPE, RENDER, etc.) — moderate volatility
  - small:  rank 201-1000 (micro-caps) — high volatility, pump candidates

Each universe has:
  - Different signal weights (tuned for that cap range)
  - Different exit targets (scaled to expected volatility)
  - Different backtesting parameters
"""

# Signal weights per universe
# Derived from backtest correlations, adjusted for each cap range's behavior
SIGNAL_WEIGHTS = {
    "large": {
        # Large caps: slow, mean-reverting. RSI and monthly growth dominate.
        "rsi": 3.0,
        "consistent_monthly_growth": 3.0,
        "volume_change": 1.5,
        "trend_conflict": 1.5,
        "fear_and_greed": 1.0,
        "sentiment": 1.0,
        "consistent_growth": 1.0,
        "sustained_volume_growth": 0.5,
        "trending": 0.5,
        "price_change": -1.0,        # Contrarian: momentum chasing hurts
        "volume_spike_24h": 1.0,
        "distance_from_ath": 0.5,
        "multi_timeframe_momentum": -0.5,  # Contrarian for large caps
    },
    "mid": {
        # Mid caps: more volatile, momentum works better short-term
        "rsi": 2.5,
        "consistent_monthly_growth": 2.0,
        "volume_change": 2.0,
        "trend_conflict": 1.5,
        "fear_and_greed": 0.5,
        "sentiment": 1.0,
        "consistent_growth": 1.0,
        "sustained_volume_growth": 1.0,
        "trending": 1.0,
        "price_change": 0.0,
        "volume_spike_24h": 2.0,
        "distance_from_ath": 1.0,
        "multi_timeframe_momentum": 0.5,
    },
    "small": {
        # Small caps: BACKTEST-VALIDATED weights (3,140 obs, 2 years)
        # Signals behave OPPOSITE to large caps here
        "rsi": 0.5,                  # Barely helps on small caps (+0.22% lift)
        "consistent_monthly_growth": 0.5,  # Slight (+0.62% 7d lift) but HARMFUL at 30d
        "volume_change": 1.5,        # Moderate (+0.81% lift)
        "trend_conflict": -1.0,      # HARMFUL on small caps (-1.31% lift) — INVERTED
        "fear_and_greed": 0.5,
        "sentiment": 1.5,            # News moves small caps harder
        "consistent_growth": 3.0,    # BEST signal for small caps (+2.31% lift!)
        "sustained_volume_growth": 1.0,  # Decent (+0.55% lift)
        "trending": 2.0,            # Trending = potential pump
        "price_change": 1.5,        # Momentum WORKS on small caps (+0.68% lift)
        # New features
        "volume_spike_24h": 3.0,    # THE key pump signal for small caps
        "distance_from_ath": 2.0,   # Far from ATH + volume = recovery pump
        "multi_timeframe_momentum": 1.5,  # Short-term momentum works
    },
}

# Exit targets per universe (% thresholds)
EXIT_TARGETS = {
    "large": {
        "take_profit_multiplier": 7,   # 7x daily vol
        "stop_loss_multiplier": 3,     # 3x daily vol
        "min_take_profit": 8.0,        # At least 8%
        "min_stop_loss": 3.0,          # At least 3%
    },
    "mid": {
        "take_profit_multiplier": 5,   # Tighter — mid caps move fast
        "stop_loss_multiplier": 3,
        "min_take_profit": 10.0,
        "min_stop_loss": 5.0,
    },
    "small": {
        "take_profit_multiplier": 4,   # Even tighter — take profits quickly
        "stop_loss_multiplier": 4,     # Wider stop — small caps are volatile
        "min_take_profit": 15.0,       # Need bigger moves to justify risk
        "min_stop_loss": 8.0,          # Wide stop to avoid being shaken out
    },
}

# Rank ranges per universe
RANK_RANGES = {
    "large": (1, 50),
    "mid": (51, 200),
    "small": (201, 1000),
    "all": (1, 1000),
}

# Stablecoins to exclude
STABLECOINS = {
    'usdt-tether', 'usdc-usd-coin', 'dai-dai', 'pyusd-paypal-usd',
    'usds-usds', 'usde-ethena-usde', 'fdusd-first-digital-usd',
    'tusd-trueusd', 'busd-binance-usd', 'gusd-gemini-dollar',
}

# Wrapped tokens to exclude
WRAPPED_TOKENS = {
    'wbtc-wrapped-bitcoin', 'weth-weth', 'steth-lido-staked-ether',
    'wsteth-wrapped-liquid-staked-ether-20', 'weeth-wrapped-eeth',
    'cbeth-coinbase-wrapped-staked-eth',
}

EXCLUDED_COINS = STABLECOINS | WRAPPED_TOKENS


def get_universe_config(universe: str) -> dict:
    """Get the full configuration for a universe."""
    if universe not in SIGNAL_WEIGHTS:
        raise ValueError(f"Unknown universe: {universe}. Choose from: {list(SIGNAL_WEIGHTS.keys())}")
    return {
        "weights": SIGNAL_WEIGHTS[universe],
        "exit_targets": EXIT_TARGETS[universe],
        "rank_range": RANK_RANGES[universe],
    }


def classify_universe(rank: int) -> str:
    """Classify a coin into a universe based on its rank."""
    if rank <= 50:
        return "large"
    elif rank <= 200:
        return "mid"
    else:
        return "small"
