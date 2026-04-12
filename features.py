"""
Feature engineering from CoinPaprika ticker data.

New signals not available from historical OHLCV alone:
  - volume_spike_24h: sudden volume increase (precedes pumps)
  - distance_from_ath: how far below all-time high (recovery potential)
  - multi_timeframe_momentum: alignment of 1h/6h/24h/7d price changes
"""

import logging
from typing import Dict, Optional, Tuple

from logging_config import setup_logging

logger = setup_logging("features", caller_file=__file__)


def compute_volume_spike_score(volume_24h_change: float) -> Tuple[float, str]:
    """
    Score based on 24h volume change from CoinPaprika ticker.

    A sudden volume spike often precedes a price move.
    Returns (score 0-1, explanation).

    Thresholds:
      > 100% increase = 1.0 (massive spike)
      > 50%  increase = 0.7
      > 20%  increase = 0.4
      > 0%   increase = 0.1
      <= 0%  decrease = 0.0
    """
    if volume_24h_change is None:
        return 0.0, "No volume data"

    if volume_24h_change > 100:
        return 1.0, f"Volume spike +{volume_24h_change:.0f}% (massive)"
    elif volume_24h_change > 50:
        return 0.7, f"Volume spike +{volume_24h_change:.0f}% (strong)"
    elif volume_24h_change > 20:
        return 0.4, f"Volume up +{volume_24h_change:.0f}% (moderate)"
    elif volume_24h_change > 0:
        return 0.1, f"Volume up +{volume_24h_change:.0f}% (slight)"
    else:
        return 0.0, f"Volume down {volume_24h_change:.0f}%"


def compute_distance_from_ath_score(percent_from_ath: float) -> Tuple[float, str]:
    """
    Score based on distance from all-time high.

    Coins far from ATH that show other positive signals
    have recovery potential. But too far = possibly dead.

    Sweet spot: -50% to -85% from ATH with volume/RSI confirmation.

    Returns (score 0-1, explanation).
    """
    if percent_from_ath is None:
        return 0.0, "No ATH data"

    dist = abs(percent_from_ath)

    if dist < 10:
        return 0.1, f"{percent_from_ath:.0f}% from ATH (near highs, limited upside)"
    elif dist < 30:
        return 0.3, f"{percent_from_ath:.0f}% from ATH (moderate pullback)"
    elif dist < 50:
        return 0.6, f"{percent_from_ath:.0f}% from ATH (significant discount)"
    elif dist < 85:
        return 1.0, f"{percent_from_ath:.0f}% from ATH (deep discount, recovery potential)"
    else:
        return 0.3, f"{percent_from_ath:.0f}% from ATH (possibly dead project)"


def compute_multi_timeframe_momentum(
    change_1h: float,
    change_6h: float,
    change_24h: float,
    change_7d: float,
) -> Tuple[float, str]:
    """
    Score based on alignment of multiple timeframes.

    When all timeframes agree (all positive or all negative),
    the trend is stronger. Mixed signals = choppy.

    Returns (score 0-1, explanation).
    """
    changes = {
        "1h": change_1h or 0,
        "6h": change_6h or 0,
        "24h": change_24h or 0,
        "7d": change_7d or 0,
    }

    positives = sum(1 for v in changes.values() if v > 0)
    negatives = sum(1 for v in changes.values() if v < 0)

    if positives == 4:
        # All timeframes bullish
        avg_change = sum(changes.values()) / 4
        return 1.0, f"All timeframes bullish (avg {avg_change:+.1f}%)"
    elif positives == 3:
        return 0.7, f"3/4 timeframes bullish"
    elif negatives == 4:
        # All bearish — could be oversold bounce setup
        avg_change = sum(changes.values()) / 4
        return 0.3, f"All timeframes bearish (avg {avg_change:+.1f}%, potential bounce)"
    elif negatives == 3:
        return 0.1, f"3/4 timeframes bearish"
    else:
        return 0.0, f"Mixed signals ({positives} up, {negatives} down)"


def extract_ticker_features(ticker_data: dict) -> Dict[str, object]:
    """
    Extract all new features from CoinPaprika ticker data.

    Parameters:
        ticker_data: dict from coinpaprika.Client.ticker(coin_id)

    Returns:
        dict with feature scores and metadata
    """
    usd = ticker_data.get("quotes", {}).get("USD", {})

    volume_spike_score, volume_spike_expl = compute_volume_spike_score(
        usd.get("volume_24h_change_24h")
    )

    distance_ath_score, distance_ath_expl = compute_distance_from_ath_score(
        usd.get("percent_from_price_ath")
    )

    mtf_score, mtf_expl = compute_multi_timeframe_momentum(
        usd.get("percent_change_1h"),
        usd.get("percent_change_6h"),
        usd.get("percent_change_24h"),
        usd.get("percent_change_7d"),
    )

    return {
        # Scores (0-1)
        "volume_spike_24h_score": volume_spike_score,
        "distance_from_ath_score": distance_ath_score,
        "multi_timeframe_momentum_score": mtf_score,
        # Raw values (for analysis)
        "volume_24h_change_pct": usd.get("volume_24h_change_24h"),
        "percent_from_ath": usd.get("percent_from_price_ath"),
        "change_1h": usd.get("percent_change_1h"),
        "change_6h": usd.get("percent_change_6h"),
        "change_24h": usd.get("percent_change_24h"),
        "change_7d": usd.get("percent_change_7d"),
        "beta_value": ticker_data.get("beta_value"),
        "ath_price": usd.get("ath_price"),
        "current_price": usd.get("price"),
        # Explanations
        "volume_spike_expl": volume_spike_expl,
        "distance_ath_expl": distance_ath_expl,
        "mtf_expl": mtf_expl,
    }
