"""Unit tests for coin_analysis scoring functions."""

import math
import pandas as pd
import numpy as np
import pytest

import sys
from pathlib import Path

# Add project root to path so imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coin_analysis import (
    calculate_price_change,
    calculate_volume_change,
    compute_rsi,
    compute_rsi_score,
    compute_sentiment_for_coin,
)
from config import MAX_POSSIBLE_SCORE


# -------------------------------------------------------------------
# RSI
# -------------------------------------------------------------------

class TestComputeRSI:
    def test_uptrend_returns_high(self):
        prices = pd.Series(np.linspace(100, 200, 30))
        assert compute_rsi(prices) == 100.0

    def test_downtrend_returns_low(self):
        prices = pd.Series(np.linspace(200, 100, 30))
        assert compute_rsi(prices) == 0.0

    def test_flat_returns_neutral(self):
        prices = pd.Series([100.0] * 30)
        assert compute_rsi(prices) == 50.0

    def test_insufficient_data_returns_neutral(self):
        prices = pd.Series([100, 101, 102])
        assert compute_rsi(prices) == 50.0

    def test_realistic_in_range(self):
        np.random.seed(42)
        prices = pd.Series(100 + np.cumsum(np.random.normal(0.2, 1.5, 60)))
        rsi = compute_rsi(prices)
        assert 0 <= rsi <= 100


class TestComputeRSIScore:
    def test_oversold_scores_one(self):
        prices = pd.Series(np.linspace(200, 100, 30))
        score, expl = compute_rsi_score(prices)
        assert score == 1.0
        assert "oversold" in expl

    def test_momentum_with_volume_scores_one(self):
        prices = pd.Series(np.linspace(100, 200, 30))
        score, expl = compute_rsi_score(prices, volume_score=2)
        assert score == 1.0
        assert "momentum" in expl

    def test_momentum_without_volume_scores_zero(self):
        prices = pd.Series(np.linspace(100, 200, 30))
        score, _ = compute_rsi_score(prices, volume_score=1)
        assert score == 0.0

    def test_neutral_scores_zero(self):
        np.random.seed(42)
        prices = pd.Series(100 + np.cumsum(np.random.normal(0, 1, 60)))
        score, _ = compute_rsi_score(prices)
        assert score == 0.0


# -------------------------------------------------------------------
# Price / Volume Change
# -------------------------------------------------------------------

class TestPriceChange:
    def test_empty_series_returns_none(self):
        assert calculate_price_change(pd.Series([], dtype=float)) is None

    def test_uptrend_positive(self):
        prices = pd.Series(range(100, 120))
        result = calculate_price_change(prices, period="short")
        assert result is not None and result > 0

    def test_downtrend_negative(self):
        prices = pd.Series(range(120, 100, -1))
        result = calculate_price_change(prices, period="short")
        assert result is not None and result < 0

    def test_zero_start_returns_none(self):
        prices = pd.Series([0.0] * 10)
        assert calculate_price_change(prices) is None


class TestVolumeChange:
    def test_empty_series_returns_none(self):
        assert calculate_volume_change(pd.Series([], dtype=float)) is None

    def test_increasing_volume_positive(self):
        volumes = pd.Series(range(1000, 2000, 50))
        result = calculate_volume_change(volumes, period="short")
        assert result is not None and result > 0

    def test_zero_start_returns_none(self):
        volumes = pd.Series([0.0] * 10)
        assert calculate_volume_change(volumes) is None


# -------------------------------------------------------------------
# Sentiment
# -------------------------------------------------------------------

class TestSentiment:
    def test_positive_news_positive_score(self):
        news = [
            {"description": "Bitcoin surges to all-time high with incredible bullish momentum"},
            {"description": "Amazing growth and positive outlook for crypto markets"},
        ]
        result = compute_sentiment_for_coin("TestCoin", news)
        assert result > 0

    def test_negative_news_negative_score(self):
        news = [
            {"description": "Crash and devastating losses across the market"},
            {"description": "Terrible performance, investors flee in panic"},
        ]
        result = compute_sentiment_for_coin("TestCoin", news)
        assert result < 0

    def test_empty_news_returns_zero(self):
        assert compute_sentiment_for_coin("TestCoin", []) == 0.0

    def test_empty_descriptions_returns_zero(self):
        news = [{"description": ""}, {"description": None}]
        assert compute_sentiment_for_coin("TestCoin", news) == 0.0

    def test_returns_float_not_int(self):
        news = [{"description": "Good news for Bitcoin today"}]
        result = compute_sentiment_for_coin("TestCoin", news)
        assert isinstance(result, float)


# -------------------------------------------------------------------
# Surge Words
# -------------------------------------------------------------------

# -------------------------------------------------------------------
# Config
# -------------------------------------------------------------------

class TestConfig:
    def test_max_possible_score_is_16(self):
        assert MAX_POSSIBLE_SCORE == 16
