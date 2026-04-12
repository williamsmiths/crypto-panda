#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Mapping, Optional, Tuple, Union
import pandas as pd
from fuzzywuzzy import fuzz

from config import (
    HIGH_VOLATILITY_THRESHOLD, MEDIUM_VOLATILITY_THRESHOLD,
    MAX_POSSIBLE_SCORE, FEAR_GREED_THRESHOLD,
    LOW_VOLUME_THRESHOLD_LARGE, LOW_VOLUME_THRESHOLD_MID, LOW_VOLUME_THRESHOLD_SMALL, analyzer
)

# Production-grade clients (with retries & UTC handling)
from api_clients import (
    call_with_retries,
    fetch_historical_ticker_data,
    fetch_fear_and_greed_index,
)
from features import extract_ticker_features

def calculate_price_change(price_data: pd.Series, period: str = "short", span: int = 7) -> Union[float, None]:
    """
    Calculate percentage change in price over a given period with EMA smoothing.
    """
    smoothed_data = price_data.ewm(span=span, adjust=False).mean()

    if period == "short":
        period_data = smoothed_data.tail(7)
    elif period == "medium":
        period_data = smoothed_data.tail(30)
    else:
        period_data = smoothed_data.tail(90)

    if period_data.empty:
        logger.warning(f"No price data for period '{period}' after smoothing.")
        return None

    start_price = period_data.iloc[0]
    end_price = period_data.iloc[-1]

    if start_price == 0:
        logger.warning("Start price is 0 → cannot compute percentage change.")
        return None

    change = (end_price - start_price) / start_price
    logger.debug(f"Price change ({period}): {change:.4f}")
    return change


def calculate_volume_change(volume_data: pd.Series, period: str = "short", span: int = 7) -> Union[float, None]:
    """
    Calculate percentage change in volume over a given period with EMA smoothing.
    """
    smoothed_data = volume_data.ewm(span=span, adjust=False).mean()

    if period == "short":
        period_data = smoothed_data.tail(7)
    elif period == "medium":
        period_data = smoothed_data.tail(30)
    else:
        period_data = smoothed_data.tail(90)

    if period_data.empty:
        logger.warning(f"No volume data for period '{period}' after smoothing.")
        return None

    start_volume = period_data.iloc[0]
    end_volume = period_data.iloc[-1]

    if start_volume == 0:
        logger.warning("Start volume is 0 → cannot compute percentage change.")
        return None

    change = (end_volume - start_volume) / start_volume
    logger.debug(f"Volume change ({period}): {change:.4f}")
    return change


# ============================
# Logging
# ============================

from logging_config import setup_logging

# Instantiate module logger
logger = setup_logging(__name__, caller_file=__file__)

# ----------------------------
# Small time helper
# ----------------------------

def utcnow() -> datetime:
    """UTC-aware 'now'."""
    return datetime.now(timezone.utc)

# ----------------------------
# RSI (Relative Strength Index)
# ----------------------------

def compute_rsi(price_series: pd.Series, period: int = 14) -> float:
    """
    Compute the Relative Strength Index (RSI) for a price series.
    Returns RSI value 0-100, or 50.0 (neutral) if insufficient data.
    """
    if len(price_series) < period + 1:
        return 50.0  # Neutral if insufficient data

    delta = price_series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()

    last_gain = avg_gain.iloc[-1]
    last_loss = avg_loss.iloc[-1]

    if pd.isna(last_gain) or pd.isna(last_loss):
        return 50.0
    if last_loss == 0:
        return 100.0 if last_gain > 0 else 50.0

    rs = last_gain / last_loss
    return float(100 - (100 / (1 + rs)))


def compute_rsi_score(price_series: pd.Series, volume_score: int = 0) -> Tuple[float, str]:
    """
    Score based on RSI: oversold (RSI < 30) or strong momentum (RSI > 70 with volume).
    Returns (score 0-1, explanation).
    """
    rsi = compute_rsi(price_series)

    if rsi < 30:
        return 1.0, f"RSI={rsi:.0f} (oversold, potential bounce)"
    elif rsi > 70 and volume_score >= 2:
        return 1.0, f"RSI={rsi:.0f} (strong momentum with volume confirmation)"
    else:
        return 0.0, f"RSI={rsi:.0f} (neutral)"


# ----------------------------
# ANALYSIS FUNCTIONS
# ----------------------------

def analyze_volume_change(volume_data: pd.Series, market_cap: int, volatility: float) -> Tuple[int, str]:
    """
    Analyze the volume changes of a cryptocurrency over three time periods.

    Returns:
        (volume_score, explanation)
    """
    market_cap_class = classify_market_cap(market_cap)
    volatility_class = classify_volatility(volatility)

    short_thr, short_max, med_thr, med_max, long_thr, long_max = get_volume_thresholds(market_cap_class, volatility_class)

    short_term_change = calculate_volume_change(volume_data, period="short")
    medium_term_change = calculate_volume_change(volume_data, period="medium")
    long_term_change = calculate_volume_change(volume_data, period="long")

    volume_score = 0
    parts: List[str] = []

    if short_thr < short_term_change < short_max:
        volume_score += 1
        parts.append(f"Short-term volume +{short_term_change*100:.2f}% (> {short_thr*100:.2f}%)")
    if med_thr < medium_term_change < med_max:
        volume_score += 1
        parts.append(f"Medium-term volume +{medium_term_change*100:.2f}% (> {med_thr*100:.2f}%)")
    if long_thr < long_term_change < long_max:
        volume_score += 1
        parts.append(f"Long-term volume +{long_term_change*100:.2f}% (> {long_thr*100:.2f}%)")

    explanation = " | ".join(parts) if parts else "No significant volume changes detected."
    return volume_score, explanation


def analyze_price_change(price_data: pd.Series, market_cap: int, volatility: float) -> Tuple[int, str]:
    """
    Analyze the price changes of a cryptocurrency over three time periods.

    Returns:
        (price_change_score, explanation)
    """
    market_cap_class = classify_market_cap(market_cap)
    volatility_class = classify_volatility(volatility)

    short_thr, med_thr, long_thr = get_price_change_thresholds(market_cap_class, volatility_class)

    st = calculate_price_change(price_data, period="short")
    mt = calculate_price_change(price_data, period="medium")
    lt = calculate_price_change(price_data, period="long")

    score = 0
    parts: List[str] = []
    if st > short_thr:
        score += 1
        parts.append(f"Short-term +{st*100:.2f}% (> {short_thr*100:.2f}%)")
    if mt > med_thr:
        score += 1
        parts.append(f"Medium-term +{mt*100:.2f}% (> {med_thr*100:.2f}%)")
    if lt > long_thr:
        score += 1
        parts.append(f"Long-term +{lt*100:.2f}% (> {long_thr*100:.2f}%)")

    explanation = " | ".join(parts) if parts else "No significant price changes detected."
    return score, explanation


def get_fuzzy_trending_score(coin_id: str, coin_name: str, trending_coins_scores: Mapping[str, float]) -> float:
    """
    Fuzzy-match coin_id/name to trending tickers; return max score if matched.
    """
    max_score = 0.0
    cid = coin_id.lower()
    cname = coin_name.lower()
    for ticker, score in trending_coins_scores.items():
        t = str(ticker).strip().lower()
        if not t:
            continue
        if fuzz.partial_ratio(t, cid) > 80 or fuzz.partial_ratio(t, cname) > 80:
            max_score = max(max_score, float(score))
    return max_score


# ---------- Compatibility wrapper (keeps your original function name) ----------


def has_consistent_monthly_growth(historical_df: pd.DataFrame) -> bool:
    """
    True if at least 18 of the last 30 days have positive price change.
    """
    df = historical_df.copy()
    df['price_change'] = df['price'].pct_change()
    last_month_df = df.tail(30)
    rising_days = (last_month_df['price_change'] > 0).sum()
    return rising_days >= 18



def fetch_google_news_for_coin(coin_name: str, max_articles: int = 20) -> list:
    """
    Fetch recent news for a coin via Google News RSS. Completely free, no API key.
    Returns list of dicts with 'title' and 'description' keys for VADER analysis.
    """
    import feedparser
    import urllib.request
    import urllib.parse
    try:
        query = urllib.parse.quote(f"{coin_name} cryptocurrency")
        url = f"https://news.google.com/rss/search?q={query}&hl=en"
        req = urllib.request.Request(url, headers={"User-Agent": "CryptoPanda/3.0"})
        resp = urllib.request.urlopen(req, timeout=10)
        feed = feedparser.parse(resp.read())
        articles = []
        for entry in feed.entries[:max_articles]:
            title = entry.get("title", "")
            articles.append({
                "title": title,
                "description": title,  # Google News RSS title contains the headline
            })
        return articles
    except Exception as e:
        logger.debug(f"Google News fetch failed for {coin_name}: {e}")
        return []


def _llm_analyze_news(coin_name: str, headlines: list) -> dict:
    """
    Use LLM to analyse news headlines with crypto-specific understanding.
    Returns dict with sentiment, catalysts, and summary.
    Falls back to VADER if LLM unavailable.
    """
    try:
        from report_generation import llm_chat_completion
        import json as _json

        headlines_text = "\n".join(f"- {h}" for h in headlines[:15])
        prompt = f"""Analyse these recent news headlines about the cryptocurrency "{coin_name}".

Headlines:
{headlines_text}

Return ONLY valid JSON with these fields:
{{
  "sentiment": <float from -1.0 (very bearish) to +1.0 (very bullish)>,
  "summary": "<one sentence summarising the news tone>",
  "catalysts": [<list of catalyst types detected, from: "exchange_listing", "partnership", "regulatory_negative", "regulatory_positive", "hack_exploit", "whale_accumulation", "technical_upgrade", "token_unlock", "lawsuit", "adoption", "none">],
  "key_risk": "<one sentence on the main risk from the news, or 'none identified'>",
  "confidence": <float 0-1, how confident you are in the sentiment reading>
}}

Rules:
- "moon", "surge", "breakout", "bullish" = positive sentiment
- "rug pull", "hack", "SEC", "lawsuit", "ban" = negative sentiment
- "exchange listing", "Binance listing", "Coinbase listing" = exchange_listing catalyst (strongly bullish for small caps)
- Be skeptical of hype — promotional headlines are less reliable than news from Reuters, Bloomberg, CoinDesk
- If headlines are mixed, sentiment should be near 0
- Return ONLY the JSON, nothing else"""

        content = llm_chat_completion(prompt, temperature=0.1)

        # Parse JSON from response
        import re
        json_match = re.search(r'\{.*\}', content, re.DOTALL)
        if json_match:
            return _json.loads(json_match.group(0))
    except Exception as e:
        logger.debug(f"LLM news analysis failed for {coin_name}: {e}")

    return None


def apply_news_confirmation(result: dict, coin_name: str) -> dict:
    """
    Stage 2: Fetch news via Google News RSS (free) and analyse using LLM
    for crypto-aware sentiment, catalyst detection, and risk identification.

    Called ONLY for shortlisted coins (top ~20), not all 200+.
    Falls back to VADER if LLM is unavailable.

    News adjusts weighted score:
      - Base adjustment: sentiment * 2.0 (range ±2.0)
      - Catalyst bonus: exchange_listing +1.0, hack_exploit -2.0, etc.
      - Confidence-scaled: adjustment * confidence

    Also tracks news velocity (article count as proxy for attention).
    """
    articles = fetch_google_news_for_coin(coin_name)

    if not articles:
        result["sentiment_score"] = 0
        result["raw_sentiment"] = 0
        result["news_flag"] = "NO_DATA"
        result["news_adjustment"] = 0
        result["news_headlines"] = []
        result["news_article_count"] = 0
        result["news_catalysts"] = []
        result["news_summary"] = ""
        result["news_key_risk"] = ""
        result["news_velocity"] = "low"
        return result

    headlines = [a["title"] for a in articles]
    article_count = len(articles)

    # News velocity: how much attention is this coin getting?
    if article_count >= 15:
        velocity = "high"
        velocity_bonus = 0.5
    elif article_count >= 8:
        velocity = "medium"
        velocity_bonus = 0.2
    else:
        velocity = "low"
        velocity_bonus = 0.0

    # Try LLM analysis first (crypto-aware), fall back to VADER
    llm_result = _llm_analyze_news(coin_name, headlines)

    if llm_result and "sentiment" in llm_result:
        raw_sentiment = float(llm_result.get("sentiment", 0))
        confidence = float(llm_result.get("confidence", 0.5))
        catalysts = llm_result.get("catalysts", [])
        summary = llm_result.get("summary", "")
        key_risk = llm_result.get("key_risk", "")
        analysis_method = "llm"
    else:
        # Fallback to VADER
        raw_sentiment = compute_sentiment_for_coin(coin_name, articles)
        confidence = 0.5
        catalysts = []
        summary = ""
        key_risk = ""
        analysis_method = "vader"

    sentiment_score = min(1.0, max(0.0, (raw_sentiment + 1.0) / 2.0))

    # Calculate news adjustment
    # Base: sentiment * 2.0, scaled by confidence
    base_adjustment = raw_sentiment * 2.0 * confidence

    # Catalyst adjustments
    catalyst_weights = {
        "exchange_listing": +1.5,
        "partnership": +0.5,
        "adoption": +0.5,
        "technical_upgrade": +0.5,
        "regulatory_positive": +0.5,
        "whale_accumulation": +0.3,
        "regulatory_negative": -1.0,
        "hack_exploit": -2.0,
        "lawsuit": -1.5,
        "token_unlock": -0.5,
    }
    catalyst_adjustment = sum(catalyst_weights.get(c, 0) for c in catalysts)

    total_adjustment = round(base_adjustment + catalyst_adjustment + velocity_bonus, 2)

    if raw_sentiment > 0.3:
        news_flag = "POSITIVE"
    elif raw_sentiment < -0.3:
        news_flag = "NEGATIVE"
    else:
        news_flag = "NEUTRAL"

    # Store all news data
    result["sentiment_score"] = round(sentiment_score, 3)
    result["raw_sentiment"] = round(raw_sentiment, 3)
    result["news_flag"] = news_flag
    result["news_adjustment"] = total_adjustment
    result["news_headlines"] = headlines[:3]
    result["news_article_count"] = article_count
    result["news_catalysts"] = catalysts
    result["news_summary"] = summary
    result["news_key_risk"] = key_risk
    result["news_velocity"] = velocity
    result["news_analysis_method"] = analysis_method

    # Adjust the weighted score
    if "weighted_score" in result:
        result["weighted_score"] = round(result["weighted_score"] + total_adjustment, 2)
        weighted_max = result.get("_weighted_max", 16.5)
        result["weighted_score_percentage"] = round(
            (result["weighted_score"] / weighted_max) * 100, 2
        ) if weighted_max else result.get("weighted_score_percentage", 0)

    return result


def analyze_coin(
    coin_id: str,
    coin_name: str,
    end_date: str,
    ticker_data: dict = None,
) -> Dict[str, object]:
    """
    Analyzes a given cryptocurrency and returns a dictionary with various analysis scores.
    """
    short_term_window = 7
    medium_term_window = 30
    long_term_window = 90

    # Use UTC-aware 'now' for windows; end_date remains the provided ISO 'YYYY-MM-DD'
    start_date_short_term = (utcnow() - timedelta(days=short_term_window)).date().isoformat()
    start_date_medium_term = (utcnow() - timedelta(days=medium_term_window)).date().isoformat()
    start_date_long_term = (utcnow() - timedelta(days=long_term_window)).date().isoformat()

    historical_df_short_term = fetch_historical_ticker_data(coin_id, start_date_short_term, end_date)
    historical_df_medium_term = fetch_historical_ticker_data(coin_id, start_date_medium_term, end_date)
    historical_df_long_term = fetch_historical_ticker_data(coin_id, start_date_long_term, end_date)

    if historical_df_long_term.empty or 'price' not in historical_df_long_term.columns:
        logger.debug(f"No valid price data available for {coin_id}.")
        return {
            "coin_id": coin_id,
            "coin_name": coin_name,
            "market_cap": 0,
            "volume_24h": 0,
            "price_change_score": 0,
            "volume_change_score": 0,
            "consistent_growth": "No",
            "sustained_volume_growth": "No",
            "fear_and_greed_index": None,
            "volume_spike_score": 0,
            "distance_ath_score": 0,
            "mtf_momentum_score": 0,
            "liquidity_risk": "High",
            "rsi_score": 0,
            "rsi_explanation": "No data",
            "cumulative_score": 0,
            "cumulative_score_percentage": 0.0,
            "explanation": f"No valid price data available for {coin_id}.",
            "coin_news": [],
            "trend_conflict": "No",
        }

    volatility = historical_df_long_term['price'].pct_change().std()

    most_recent_market_cap = int(historical_df_long_term['market_cap'].iloc[-1])
    most_recent_volume_24h = int(historical_df_long_term['volume_24h'].iloc[-1])

    price_change_score, price_change_explanation = analyze_price_change(historical_df_long_term['price'], most_recent_market_cap, volatility)
    volume_score, volume_explanation = analyze_volume_change(historical_df_long_term['volume_24h'], most_recent_market_cap, volatility)

    consistent_growth = has_consistent_weekly_growth(historical_df_short_term)
    consistent_growth_score = 1 if consistent_growth else 0

    sustained_volume_growth = has_sustained_volume_growth(historical_df_short_term)
    sustained_volume_growth_score = 1 if sustained_volume_growth else 0

    fear_and_greed_index = fetch_fear_and_greed_index()
    fear_and_greed_score = min(1.0, max(0.0, (fear_and_greed_index - 40) / 60.0)) if fear_and_greed_index is not None else 0

    # CoinPaprika ticker features (real-time signals)
    ticker_features = extract_ticker_features(ticker_data) if ticker_data else {}
    volume_spike_score = ticker_features.get("volume_spike_24h_score", 0)
    distance_ath_score = ticker_features.get("distance_from_ath_score", 0)
    mtf_momentum_score = ticker_features.get("multi_timeframe_momentum_score", 0)

    consistent_monthly_growth = has_consistent_monthly_growth(historical_df_medium_term)
    consistent_monthly_growth_score = 1 if consistent_monthly_growth else 0

    market_cap_class = classify_market_cap(most_recent_market_cap)
    liquidity_risk = classify_liquidity_risk(most_recent_volume_24h, market_cap_class)

    trend_conflict_score = 2 if (consistent_monthly_growth_score and not consistent_growth_score) else 0

    # RSI indicator
    rsi_score, rsi_explanation = compute_rsi_score(historical_df_long_term['price'], volume_score)

    # Equal-weighted score (legacy, kept for comparison)
    cumulative_score = (
        volume_score + consistent_growth_score + sustained_volume_growth_score +
        fear_and_greed_score + price_change_score +
        consistent_monthly_growth_score +
        trend_conflict_score + rsi_score +
        volume_spike_score + distance_ath_score + mtf_momentum_score
    )

    max_possible_score = MAX_POSSIBLE_SCORE
    cumulative_score_percentage = (cumulative_score / max_possible_score) * 100 if max_possible_score else 0.0

    # Evidence-weighted score (derived from backtest signal correlations)
    _SIGNAL_WEIGHTS = {
        "rsi": 3.0,                       # Best 7d signal (+3.48% lift)
        "consistent_monthly_growth": 3.0,  # Best 30d signal (+13.72% lift)
        "volume_change": 2.0,             # Good 30d signal (+6.65% lift)
        "trend_conflict": 1.5,            # Decent 30d signal (+3.96% lift)
        "fear_and_greed": 1.0,            # Conceptually sound
        "consistent_growth": 1.0,         # Marginal (+1.15% lift)
        "sustained_volume_growth": 0.5,   # Mixed (-0.82%/+2.74% lift)
        "price_change": -1.0,             # INVERTED: momentum chasing hurts 7d returns
        # Ticker features
        "volume_spike_24h": 2.0,          # Real-time volume surge detection
        "distance_from_ath": 1.5,         # Recovery potential signal
        "multi_timeframe_momentum": 1.0,  # Timeframe alignment
    }
    weighted_score = (
        _SIGNAL_WEIGHTS["rsi"] * rsi_score +
        _SIGNAL_WEIGHTS["consistent_monthly_growth"] * consistent_monthly_growth_score +
        _SIGNAL_WEIGHTS["volume_change"] * (volume_score / 3.0) +
        _SIGNAL_WEIGHTS["trend_conflict"] * (trend_conflict_score / 2.0) +
        _SIGNAL_WEIGHTS["fear_and_greed"] * fear_and_greed_score +
        _SIGNAL_WEIGHTS["consistent_growth"] * consistent_growth_score +
        _SIGNAL_WEIGHTS["sustained_volume_growth"] * sustained_volume_growth_score +
        _SIGNAL_WEIGHTS["price_change"] * (price_change_score / 3.0) +
        _SIGNAL_WEIGHTS["volume_spike_24h"] * volume_spike_score +
        _SIGNAL_WEIGHTS["distance_from_ath"] * distance_ath_score +
        _SIGNAL_WEIGHTS["multi_timeframe_momentum"] * mtf_momentum_score
    )
    weighted_max = sum(abs(w) for w in _SIGNAL_WEIGHTS.values())
    weighted_score_percentage = round((weighted_score / weighted_max) * 100, 2) if weighted_max else 0.0
    _weighted_max = weighted_max  # stored for stage 2 news adjustment

    # Exit strategy targets (volatility-scaled)
    vol_daily = volatility if volatility and not pd.isna(volatility) else 0.03
    take_profit_target = round(max(8.0, vol_daily * 100 * 7), 1)
    stop_loss_target = round(max(3.0, vol_daily * 100 * 3), 1)

    # Build explanation
    explanation = (
        f"{coin_name} ({coin_id}) analysis: "
        f"Liquidity Risk: {liquidity_risk}, "
        f"Price Change Score: {'Significant' if price_change_score else 'No significant change'} ({price_change_explanation}), "
        f"Volume Change Score: {'Significant' if volume_score else 'No significant change'} ({volume_explanation}), "
        f"Consistent Price Growth: {'Yes' if consistent_growth_score else 'No'}, "
        f"Sustained Volume Growth: {'Yes' if sustained_volume_growth_score else 'No'}, "
        f"Fear and Greed Index: {fear_and_greed_index if isinstance(fear_and_greed_index, int) else 'N/A'}, "
        f"Volume Spike: {ticker_features.get('volume_spike_expl', 'N/A')}, "
        f"ATH Distance: {ticker_features.get('distance_ath_expl', 'N/A')}, "
        f"Multi-TF Momentum: {ticker_features.get('mtf_expl', 'N/A')}, "
        f"Market Cap: {most_recent_market_cap}, "
        f"Volume (24h): {most_recent_volume_24h}, "
        f"Cumulative Surge Score: {cumulative_score} ({cumulative_score_percentage:.2f}%), "
        f"Consistent Monthly Growth: {'Yes' if consistent_monthly_growth_score else 'No'}, "
        f"Trend Conflict: {'Yes' if trend_conflict_score else 'No'} (Monthly growth without short-term support), "
        f"RSI: {rsi_explanation}"
    )

    return {
        "coin_id": coin_id,
        "coin_name": coin_name,
        "market_cap": most_recent_market_cap,
        "volume_24h": most_recent_volume_24h,
        "price_change_score": int(price_change_score),
        "volume_change_score": int(volume_score),
        "consistent_growth": "Yes" if consistent_growth_score else "No",
        "sustained_volume_growth": "Yes" if sustained_volume_growth_score else "No",
        "fear_and_greed_index": int(fear_and_greed_index) if fear_and_greed_index is not None else None,
        "volume_spike_score": volume_spike_score,
        "distance_ath_score": distance_ath_score,
        "mtf_momentum_score": mtf_momentum_score,
        "volume_spike_expl": ticker_features.get("volume_spike_expl", ""),
        "distance_ath_expl": ticker_features.get("distance_ath_expl", ""),
        "mtf_expl": ticker_features.get("mtf_expl", ""),
        "percent_from_ath": ticker_features.get("percent_from_ath"),
        "liquidity_risk": liquidity_risk,
        "rsi_score": rsi_score,
        "rsi_explanation": rsi_explanation,
        "cumulative_score": cumulative_score,
        "cumulative_score_percentage": round(cumulative_score_percentage, 2),
        "weighted_score": round(weighted_score, 2),
        "weighted_score_percentage": weighted_score_percentage,
        "_weighted_max": _weighted_max,
        "take_profit_target_pct": take_profit_target,
        "stop_loss_target_pct": stop_loss_target,
        "explanation": explanation,
        "trend_conflict": "Yes" if trend_conflict_score else "No",
    }

# ----------------------------
# MATCHING & THRESHOLDS
# ----------------------------


def get_price_change_thresholds(market_cap_class: str, volatility_class: str) -> Tuple[float, float, float]:
    """
    Returns (short, medium, long) price change thresholds for market cap & volatility classes.
    """
    thresholds = {
        ("Large", "High"): (0.03, 0.02, 0.01),
        ("Large", "Low"): (0.015, 0.01, 0.005),
        ("Mid", "High"): (0.05, 0.03, 0.02),
        ("Mid", "Medium"): (0.03, 0.02, 0.015),
        ("Mid", "Low"): (0.02, 0.015, 0.01),
        ("Small", "High"): (0.07, 0.05, 0.03),
        ("Small", "Medium"): (0.05, 0.03, 0.02),
        ("Small", "Low"): (0.03, 0.02, 0.015)
    }
    return thresholds.get((market_cap_class, volatility_class), (0.03, 0.02, 0.01))


def has_sustained_volume_growth(historical_df: pd.DataFrame) -> bool:
    """
    Returns True if >= 4 of last 7 days have positive volume change.
    """
    df = historical_df.copy()
    df['volume_change'] = df['volume_24h'].pct_change()
    last_week_df = df.tail(7)
    rising_volume_days = (last_week_df['volume_change'] > 0).sum()
    return rising_volume_days >= 4


def classify_liquidity_risk(volume_24h: float, market_cap_class: str) -> str:
    """
    Classify liquidity risk based on trading volume and market cap class.
    """
    if market_cap_class == "Large":
        if volume_24h < LOW_VOLUME_THRESHOLD_LARGE:
            return "High"
        elif volume_24h < LOW_VOLUME_THRESHOLD_LARGE * 2:
            return "Medium"
        else:
            return "Low"
    elif market_cap_class == "Mid":
        if volume_24h < LOW_VOLUME_THRESHOLD_MID:
            return "High"
        elif volume_24h < LOW_VOLUME_THRESHOLD_MID * 2:
            return "Medium"
        else:
            return "Low"
    else:  # Small
        if volume_24h < LOW_VOLUME_THRESHOLD_SMALL:
            return "High"
        elif volume_24h < LOW_VOLUME_THRESHOLD_SMALL * 2:
            return "Medium"
        else:
            return "Low"


def has_consistent_weekly_growth(historical_df: pd.DataFrame) -> bool:
    """
    Returns True if >= 4 of last 7 days have positive price change.
    """
    df = historical_df.copy()
    df['price_change'] = df['price'].pct_change()
    last_week_df = df.tail(7)
    rising_days = (last_week_df['price_change'] > 0).sum()
    return rising_days >= 4


def get_volume_thresholds(market_cap_class: str, volatility_class: str) -> Tuple[float, float, float, float, float, float]:
    """
    Returns (short_thr, short_max, med_thr, med_max, long_thr, long_max) for volume ratios.
    """
    thresholds = {
        ("Large", "High"): (2, 4, 1.5, 3, 1.2, 2),
        ("Large", "Medium"): (1.5, 3, 1.2, 2, 1, 1.5),
        ("Large", "Low"): (1.2, 2, 1.1, 1.5, 1, 1.2),
        ("Mid", "High"): (3, 6, 2, 4, 1.5, 2.5),
        ("Mid", "Medium"): (2, 4, 1.5, 3, 1.2, 2),
        ("Mid", "Low"): (1.5, 3, 1.2, 2, 1, 1.5),
        ("Small", "High"): (5, 10, 3, 6, 2, 4),
        ("Small", "Medium"): (3, 6, 2, 4, 1.5, 2.5),
        ("Small", "Low"): (2, 4, 1.5, 3, 1.2, 2)
    }
    return thresholds.get((market_cap_class, volatility_class), (2, 4, 1.5, 3, 1.2, 2))



def classify_volatility(volatility: float) -> str:
    """
    Classify a volatility value as "High", "Medium", or "Low".
    """
    if volatility > HIGH_VOLATILITY_THRESHOLD:
        return "High"
    elif volatility > MEDIUM_VOLATILITY_THRESHOLD:
        return "Medium"
    else:
        return "Low"


def classify_market_cap(market_cap: int) -> str:
    """
    Classify a market capitalization as "Large", "Mid", or "Small".
    """
    if market_cap > 10_000_000_000:
        return "Large"
    elif market_cap > 1_000_000_000:
        return "Mid"
    else:
        return "Small"


def compute_sentiment_for_coin(coin_name: str, news_data: List[Mapping[str, str]]) -> float:
    """
    Computes the average compound sentiment for a given coin based on its news data.

    Returns:
        Average VADER compound sentiment (-1.0 to 1.0), or 0.0 if no data.
    """
    sentiments: List[float] = []
    for news_item in news_data:
        description = news_item.get('description', '')
        if isinstance(description, str) and description.strip():
            sentiment_score = float(analyzer.polarity_scores(description)['compound'])
            sentiments.append(sentiment_score)

    return (sum(sentiments) / len(sentiments)) if sentiments else 0.0


