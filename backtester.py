#!/usr/bin/env python3
"""
Crypto-Panda Backtester

Validates whether the scoring system predicts actual price surges.

For each historical week over the past N months:
  1. Fetch price/volume data as it existed at that point in time
  2. Score each coin using the same logic as the live system
  3. Record what the price actually did 7 and 30 days later
  4. Correlate scores with actual returns

Usage:
    python backtester.py [--weeks 24] [--top-coins 50] [--output backtest_results.csv]
"""

import sys
import os
import argparse
import json
import time
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from logging_config import setup_logging
from coin_analysis import (
    compute_rsi,
    analyze_price_change,
    analyze_volume_change,
    has_consistent_weekly_growth,
    has_consistent_monthly_growth,
    has_sustained_volume_growth,
    classify_market_cap,
    classify_liquidity_risk,
)
from config import MAX_POSSIBLE_SCORE, LOG_DIR, COIN_PAPRIKA_API_KEY
from api_clients import (
    fetch_historical_ticker_data,
    call_with_retries,
    filter_active_and_ranked_coins,
    _coinpaprika_client,
)

logger = setup_logging("backtester", caller_file=__file__)

# Data source: CoinPaprika Pro (primary) with CoinGecko free (fallback)
USE_COINPAPRIKA = bool(COIN_PAPRIKA_API_KEY)

try:
    from pycoingecko import CoinGeckoAPI
    cg = CoinGeckoAPI()
    HAS_COINGECKO = True
except ImportError:
    cg = None
    HAS_COINGECKO = False


def score_coin_from_historical(coin_id: str, price_df: pd.DataFrame) -> dict:
    """
    Score a coin using ONLY price/volume data (no API-dependent signals).
    Returns the sub-scores that can be computed from historical OHLCV data.

    Signals we CAN backtest (price/volume derived):
      - price_change_score (0-3)
      - volume_change_score (0-3)
      - consistent_growth_score (0-1)
      - sustained_volume_growth_score (0-1)
      - consistent_monthly_growth_score (0-1)
      - trend_conflict_score (0-2)
      - rsi_score (0-1)
      - liquidity_risk

    Signals we CANNOT backtest (require live API calls):
      - tweet_score, sentiment_score, surge_score, digest_score
      - trending_score, fear_and_greed_score, event_score
    """
    if price_df.empty or len(price_df) < 7:
        return None

    try:
        # Split into windows
        short_term = price_df.tail(7)
        medium_term = price_df.tail(30)
        long_term = price_df  # full 90 days

        if 'price' not in long_term.columns or long_term['price'].dropna().empty:
            return None

        market_cap = int(long_term['market_cap'].iloc[-1]) if 'market_cap' in long_term.columns else 0
        volume_24h = int(long_term['volume_24h'].iloc[-1]) if 'volume_24h' in long_term.columns else 0
        current_price = float(long_term['price'].iloc[-1])

        if market_cap == 0 or current_price == 0:
            return None

        volatility = long_term['price'].pct_change().std()
        if pd.isna(volatility):
            volatility = 0.03

        # Score components
        price_change_score, _ = analyze_price_change(long_term['price'], market_cap, volatility)
        volume_score, _ = analyze_volume_change(long_term['volume_24h'], market_cap, volatility)

        consistent_growth = has_consistent_weekly_growth(short_term) if len(short_term) >= 7 else False
        consistent_growth_score = 1 if consistent_growth else 0

        sustained_volume = has_sustained_volume_growth(short_term) if len(short_term) >= 7 else False
        sustained_volume_growth_score = 1 if sustained_volume else 0

        consistent_monthly = has_consistent_monthly_growth(medium_term) if len(medium_term) >= 18 else False
        consistent_monthly_growth_score = 1 if consistent_monthly else 0

        trend_conflict_score = 2 if (consistent_monthly_growth_score and not consistent_growth_score) else 0

        # RSI
        rsi = compute_rsi(long_term['price'])
        if rsi < 30:
            rsi_score = 1.0
        elif rsi > 70 and volume_score >= 2:
            rsi_score = 1.0
        else:
            rsi_score = 0.0

        market_cap_class = classify_market_cap(market_cap)
        liquidity_risk = classify_liquidity_risk(volume_24h, market_cap_class)

        # Equal-weighted score (original)
        backtestable_score = (
            price_change_score + volume_score +
            consistent_growth_score + sustained_volume_growth_score +
            consistent_monthly_growth_score + trend_conflict_score + rsi_score
        )
        backtestable_max = 12

        # Evidence-weighted score (based on backtest correlations)
        # RSI and monthly growth are strongest; price momentum is inverted (contrarian)
        WEIGHTS = {
            "rsi": 3.0,                    # Best 7d signal
            "consistent_monthly_growth": 3.0,  # Best 30d signal
            "volume_change": 2.0,          # Good 30d signal
            "trend_conflict": 1.5,         # Decent 30d signal
            "consistent_growth": 1.0,      # Marginal
            "sustained_volume_growth": 0.5, # Mixed
            "price_change": -1.0,          # INVERTED: momentum chasing hurts 7d
        }
        weighted_score = (
            WEIGHTS["rsi"] * rsi_score +
            WEIGHTS["consistent_monthly_growth"] * consistent_monthly_growth_score +
            WEIGHTS["volume_change"] * (volume_score / 3.0) +  # normalize to 0-1
            WEIGHTS["trend_conflict"] * (trend_conflict_score / 2.0) +
            WEIGHTS["consistent_growth"] * consistent_growth_score +
            WEIGHTS["sustained_volume_growth"] * sustained_volume_growth_score +
            WEIGHTS["price_change"] * (price_change_score / 3.0)
        )
        weighted_max = sum(abs(w) for w in WEIGHTS.values())  # 12.0
        weighted_pct = round((weighted_score / weighted_max) * 100, 2) if weighted_max else 0

        return {
            "coin_id": coin_id,
            "current_price": current_price,
            "market_cap": market_cap,
            "volume_24h": volume_24h,
            "price_change_score": price_change_score,
            "volume_change_score": volume_score,
            "consistent_growth_score": consistent_growth_score,
            "sustained_volume_growth_score": sustained_volume_growth_score,
            "consistent_monthly_growth_score": consistent_monthly_growth_score,
            "trend_conflict_score": trend_conflict_score,
            "rsi_score": rsi_score,
            "rsi_value": rsi,
            "liquidity_risk": liquidity_risk,
            "backtestable_score": backtestable_score,
            "backtestable_pct": round((backtestable_score / backtestable_max) * 100, 2),
            "weighted_score": round(weighted_score, 2),
            "weighted_pct": weighted_pct,
        }
    except Exception as e:
        logger.debug(f"Error scoring {coin_id}: {e}")
        return None


def detect_market_regime(btc_prices: pd.Series) -> str:
    """
    Detect whether we're in a bull, bear, or sideways market based on BTC.
    Uses 50-day and 200-day moving averages (golden/death cross).

    Returns: 'bull', 'bear', or 'sideways'
    """
    if len(btc_prices) < 200:
        return "unknown"

    ma50 = btc_prices.rolling(50).mean().iloc[-1]
    ma200 = btc_prices.rolling(200).mean().iloc[-1]
    current = btc_prices.iloc[-1]

    if pd.isna(ma50) or pd.isna(ma200):
        return "unknown"

    # Bull: price above both MAs and 50MA > 200MA (golden cross)
    if current > ma50 and ma50 > ma200:
        return "bull"
    # Bear: price below both MAs and 50MA < 200MA (death cross)
    elif current < ma50 and ma50 < ma200:
        return "bear"
    else:
        return "sideways"


def simulate_exit_strategies(entry_price: float, future_prices: list, hist_volatility: float):
    """
    Simulate different exit strategies on a price series.

    Returns dict with realized return for each strategy:
    - hold: hold to end of window
    - trailing_stop: sell when price drops X% from peak
    - take_profit: sell when price hits target
    - trailing_take_profit: take profit target with trailing stop after
    """
    if not future_prices or entry_price == 0:
        return {}

    vol_daily = hist_volatility if hist_volatility > 0 else 0.03

    # Strategy parameters (volatility-scaled)
    trailing_stop_pct = max(3.0, vol_daily * 100 * 3)   # 3x daily vol, min 3%
    take_profit_pct = max(8.0, vol_daily * 100 * 7)      # 7x daily vol, min 8%

    results = {
        "exit_trailing_stop_pct": trailing_stop_pct,
        "exit_take_profit_pct": take_profit_pct,
    }

    # Hold to end
    results["return_hold"] = round(((future_prices[-1] - entry_price) / entry_price) * 100, 2)

    # Trailing stop
    peak = entry_price
    for i, price in enumerate(future_prices):
        peak = max(peak, price)
        drawdown_from_peak = ((price - peak) / peak) * 100
        if drawdown_from_peak < -trailing_stop_pct:
            results["return_trailing_stop"] = round(((price - entry_price) / entry_price) * 100, 2)
            results["exit_day_trailing_stop"] = i + 1
            break
    else:
        # Never triggered — hold to end
        results["return_trailing_stop"] = results["return_hold"]
        results["exit_day_trailing_stop"] = len(future_prices)

    # Take profit
    for i, price in enumerate(future_prices):
        gain = ((price - entry_price) / entry_price) * 100
        if gain >= take_profit_pct:
            results["return_take_profit"] = round(gain, 2)
            results["exit_day_take_profit"] = i + 1
            break
    else:
        results["return_take_profit"] = results["return_hold"]
        results["exit_day_take_profit"] = len(future_prices)

    # Combined: take profit OR trailing stop (whichever triggers first)
    peak = entry_price
    for i, price in enumerate(future_prices):
        peak = max(peak, price)
        gain = ((price - entry_price) / entry_price) * 100
        drawdown_from_peak = ((price - peak) / peak) * 100

        if gain >= take_profit_pct:
            results["return_combined"] = round(gain, 2)
            results["exit_day_combined"] = i + 1
            results["exit_reason_combined"] = "take_profit"
            break
        elif drawdown_from_peak < -trailing_stop_pct:
            results["return_combined"] = round(gain, 2)
            results["exit_day_combined"] = i + 1
            results["exit_reason_combined"] = "stop_loss"
            break
    else:
        results["return_combined"] = results["return_hold"]
        results["exit_day_combined"] = len(future_prices)
        results["exit_reason_combined"] = "expired"

    return results


def fetch_full_history_coingecko(coin_id: str, days: int = 180) -> pd.DataFrame:
    """Fetch history from CoinGecko (free fallback)."""
    if not HAS_COINGECKO or cg is None:
        return pd.DataFrame()
    try:
        data = cg.get_coin_market_chart_by_id(coin_id, vs_currency='usd', days=days)
        prices = pd.DataFrame(data['prices'], columns=['timestamp', 'price'])
        volumes = pd.DataFrame(data['total_volumes'], columns=['timestamp', 'volume_24h'])
        mcaps = pd.DataFrame(data['market_caps'], columns=['timestamp', 'market_cap'])

        df = prices.merge(volumes, on='timestamp').merge(mcaps, on='timestamp')
        df['date'] = pd.to_datetime(df['timestamp'], unit='ms').dt.date
        df = df.groupby('date').last().reset_index()
        df['coin_id'] = coin_id
        return df
    except Exception as e:
        logger.debug(f"CoinGecko error for {coin_id}: {e}")
        return pd.DataFrame()


def fetch_full_history_coinpaprika(coin_id: str, start_date: str, end_date: str) -> pd.DataFrame:
    """Fetch history from CoinPaprika Pro."""
    return fetch_historical_ticker_data(coin_id, start_date, end_date)


def run_backtest(weeks: int = 24, top_n: int = 50, output_file: str = None, universe: str = "all"):
    """
    Run the full backtest over the specified number of weeks.
    Uses CoinPaprika Pro if available, falls back to CoinGecko free.

    Args:
        universe: "large" (rank 1-50), "mid" (51-200), "small" (201-1000), "all"
    """
    from coin_universe import RANK_RANGES, EXCLUDED_COINS, get_universe_config

    if output_file is None:
        output_file = os.path.join(LOG_DIR, f"backtest_{universe}.csv")

    Path(LOG_DIR).mkdir(parents=True, exist_ok=True)

    rank_min, rank_max = RANK_RANGES.get(universe, (1, 1000))
    logger.info(f"Universe: {universe} (rank {rank_min}-{rank_max})")

    if USE_COINPAPRIKA:
        logger.info(f"Using CoinPaprika Pro for data")
        raw_coins = call_with_retries(_coinpaprika_client.coins)
        # Filter by rank range + active + not excluded
        all_coins = [
            c for c in raw_coins
            if c.get("is_active") and not c.get("is_new")
            and c.get("rank") is not None
            and rank_min <= c.get("rank", 0) <= rank_max
            and c['id'] not in EXCLUDED_COINS
        ][:top_n]
        coin_ids = [c['id'] for c in all_coins]
        coin_names = {c['id']: c['name'] for c in all_coins}
        data_source = "coinpaprika"
    elif HAS_COINGECKO:
        logger.info(f"Using CoinGecko free (no CoinPaprika API key)")
        # CoinGecko doesn't support rank filtering well — fetch more and slice
        per_page = min(rank_max, 250)
        coins_list = cg.get_coins_markets(vs_currency='usd', order='market_cap_desc', per_page=per_page, page=1)
        if not coins_list:
            logger.error("Could not fetch coin list")
            return
        coins_list = [
            c for c in coins_list
            if c['id'] not in EXCLUDED_COINS
            and c.get('market_cap_rank') is not None
            and rank_min <= c.get('market_cap_rank', 0) <= rank_max
        ][:top_n]
        coin_ids = [c['id'] for c in coins_list]
        coin_names = {c['id']: c['name'] for c in coins_list}
        data_source = "coingecko"
    else:
        logger.error("No data source available. Set COIN_PAPRIKA_API_KEY or install pycoingecko.")
        return

    logger.info(f"Backtesting {len(coin_ids)} coins over {weeks} weeks via {data_source} ({universe} caps)")

    # Calculate date range
    end_backtest = datetime.now(timezone.utc) - timedelta(days=30)
    total_days = weeks * 7 + 120  # extra 120 days for 90-day lookback + 30-day outcome
    start_fetch = (end_backtest - timedelta(days=total_days)).strftime("%Y-%m-%d")
    end_fetch = (datetime.now(timezone.utc)).strftime("%Y-%m-%d")

    # Fetch full history for all coins upfront
    logger.info("Fetching historical data for all coins...")
    history_cache = {}
    for i, coin_id in enumerate(coin_ids):
        logger.info(f"Fetching {coin_id} ({i+1}/{len(coin_ids)})...")
        if data_source == "coinpaprika":
            df = fetch_full_history_coinpaprika(coin_id, start_fetch, end_fetch)
        else:
            fetch_days = min(365, total_days)
            df = fetch_full_history_coingecko(coin_id, days=fetch_days)

        if not df.empty:
            history_cache[coin_id] = df

        # Rate limiting
        if data_source == "coingecko":
            time.sleep(1.2)  # CoinGecko free: ~50 calls/min
        else:
            time.sleep(0.15)  # CoinPaprika Pro: much higher limits

    logger.info(f"Got history for {len(history_cache)}/{len(coin_ids)} coins via {data_source}")

    # Generate weekly test dates (going back from 30 days ago so we have outcome data)
    end_backtest = datetime.now(timezone.utc) - timedelta(days=30)
    test_dates = []
    for w in range(weeks):
        d = end_backtest - timedelta(weeks=w)
        test_dates.append(d.strftime("%Y-%m-%d"))
    test_dates.reverse()

    logger.info(f"Test dates: {test_dates[0]} to {test_dates[-1]}")

    all_results = []
    total_tasks = len(test_dates) * len(history_cache)
    completed = 0

    # Get BTC history for market regime detection
    btc_history = history_cache.get("bitcoin", pd.DataFrame())

    for score_date in test_dates:
        score_dt = datetime.strptime(score_date, "%Y-%m-%d").date()
        date_7d = score_dt + timedelta(days=7)
        date_30d = score_dt + timedelta(days=30)

        # Detect market regime from BTC as of this date
        if not btc_history.empty:
            btc_up_to_date = btc_history[btc_history['date'] <= score_dt]
            market_regime = detect_market_regime(btc_up_to_date['price']) if len(btc_up_to_date) >= 200 else "unknown"
        else:
            market_regime = "unknown"

        logger.info(f"--- Scoring date: {score_date} (regime: {market_regime}) ---")

        for coin_id, full_df in history_cache.items():
            completed += 1
            if completed % 50 == 0:
                logger.info(f"Progress: {completed}/{total_tasks} ({100*completed/total_tasks:.0f}%)")

            # Slice 90 days of history up to score_date
            hist_df = full_df[full_df['date'] <= score_dt].tail(90).copy()
            if hist_df.empty or len(hist_df) < 7:
                continue

            # Score the coin as of score_date
            scores = score_coin_from_historical(coin_id, hist_df)
            if scores is None:
                continue

            if scores["liquidity_risk"] == "High":
                continue

            price_at_score = scores["current_price"]

            # Get the full price window for outcome measurement
            future_7d = full_df[(full_df['date'] > score_dt) & (full_df['date'] <= date_7d)]
            future_30d = full_df[(full_df['date'] > score_dt) & (full_df['date'] <= date_30d)]

            # Endpoint prices
            df_7d_end = full_df[full_df['date'] == date_7d]
            df_30d_end = full_df[full_df['date'] == date_30d]
            price_7d = float(df_7d_end['price'].iloc[0]) if not df_7d_end.empty else None
            price_30d = float(df_30d_end['price'].iloc[0]) if not df_30d_end.empty else None

            if price_7d is None and price_30d is None:
                continue

            # Endpoint returns
            ret_7d = ((price_7d - price_at_score) / price_at_score * 100) if price_7d else None
            ret_30d = ((price_30d - price_at_score) / price_at_score * 100) if price_30d else None

            # Coin's historical volatility (annualized daily std)
            hist_volatility = hist_df['price'].pct_change().std() if len(hist_df) > 5 else 0.03
            vol_7d = hist_volatility * (7 ** 0.5) * 100   # expected % move over 7 days
            vol_30d = hist_volatility * (30 ** 0.5) * 100  # expected % move over 30 days

            # Peak and trough within each window
            def window_stats(window_df, entry_price):
                if window_df.empty or entry_price == 0:
                    return 0, 0, 0
                prices = window_df['price'].values
                peak_ret = ((max(prices) - entry_price) / entry_price) * 100
                trough_ret = ((min(prices) - entry_price) / entry_price) * 100
                max_drawdown = 0
                running_max = entry_price
                for p in prices:
                    running_max = max(running_max, p)
                    dd = ((p - running_max) / running_max) * 100
                    max_drawdown = min(max_drawdown, dd)
                return round(peak_ret, 2), round(trough_ret, 2), round(max_drawdown, 2)

            peak_7d, trough_7d, drawdown_7d = window_stats(future_7d, price_at_score)
            peak_30d, trough_30d, drawdown_30d = window_stats(future_30d, price_at_score)

            # Volatility-adjusted surge detection
            # A "surge" = peak return exceeds 2x the coin's expected move for that window
            surge_threshold_7d = max(5.0, vol_7d * 2)   # at least 5%, or 2x expected vol
            surge_threshold_30d = max(10.0, vol_30d * 2) # at least 10%, or 2x expected vol

            # Pullback detection: price dropped > 1.5x expected vol then recovered > 50% of drop
            pullback_7d = (trough_7d < -vol_7d * 1.5) and (ret_7d is not None and ret_7d > trough_7d * 0.5)
            pullback_30d = (trough_30d < -vol_30d * 1.5) and (ret_30d is not None and ret_30d > trough_30d * 0.5)

            # Sharpe-like risk-adjusted return (return / volatility)
            risk_adj_7d = (ret_7d / vol_7d) if (ret_7d is not None and vol_7d > 0) else None
            risk_adj_30d = (ret_30d / vol_30d) if (ret_30d is not None and vol_30d > 0) else None

            result = {
                "score_date": score_date,
                "coin_id": coin_id,
                "coin_name": coin_names.get(coin_id, coin_id),
                "price_at_score": price_at_score,
                "price_7d_later": price_7d,
                "price_30d_later": price_30d,
                "return_7d_pct": round(ret_7d, 2) if ret_7d is not None else None,
                "return_30d_pct": round(ret_30d, 2) if ret_30d is not None else None,
                # New: volatility-adjusted metrics
                "hist_volatility": round(hist_volatility * 100, 2),
                "peak_7d_pct": peak_7d,
                "trough_7d_pct": trough_7d,
                "drawdown_7d_pct": drawdown_7d,
                "peak_30d_pct": peak_30d,
                "trough_30d_pct": trough_30d,
                "drawdown_30d_pct": drawdown_30d,
                "risk_adj_7d": round(risk_adj_7d, 3) if risk_adj_7d is not None else None,
                "risk_adj_30d": round(risk_adj_30d, 3) if risk_adj_30d is not None else None,
                # Surge: peak exceeds volatility-adjusted threshold
                "surged_7d": peak_7d > surge_threshold_7d,
                "surged_30d": peak_30d > surge_threshold_30d,
                "surge_threshold_7d": round(surge_threshold_7d, 2),
                "surge_threshold_30d": round(surge_threshold_30d, 2),
                # Pullback: significant drop followed by recovery
                "pullback_7d": pullback_7d,
                "pullback_30d": pullback_30d,
                # Market regime
                "market_regime": market_regime,
                **{k: v for k, v in scores.items() if k != "current_price"},
            }

            # Simulate exit strategies on 30-day window
            if not future_30d.empty:
                future_prices_30d = future_30d['price'].tolist()
                exit_results = simulate_exit_strategies(price_at_score, future_prices_30d, hist_volatility)
                result.update({f"exit_{k}" if not k.startswith("exit_") else k: v for k, v in exit_results.items()})

            all_results.append(result)

    if not all_results:
        logger.error("No results produced. Check API access.")
        return

    df = pd.DataFrame(all_results)
    df.to_csv(output_file, index=False)
    logger.info(f"Backtest results saved to {output_file} ({len(df)} rows)")

    # Analyze
    analyze_backtest(df)


def analyze_backtest(df: pd.DataFrame):
    """Analyze backtest results and print report."""
    output_dir = LOG_DIR
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    print("\n" + "=" * 70)
    print("CRYPTO-PANDA BACKTEST REPORT")
    print("=" * 70)

    print(f"\nDataset: {len(df)} coin-date observations")
    print(f"Date range: {df['score_date'].min()} to {df['score_date'].max()}")
    print(f"Coins: {df['coin_id'].nunique()}")

    # --- Overall Score vs Returns ---
    score_col = "backtestable_pct"

    for horizon, ret_col, surge_col in [
        ("7-day", "return_7d_pct", "surged_7d"),
        ("30-day", "return_30d_pct", "surged_30d"),
    ]:
        valid = df.dropna(subset=[ret_col])
        if valid.empty:
            continue

        print(f"\n--- {horizon} Returns ---")
        print(f"Observations: {len(valid)}")
        print(f"Avg return: {valid[ret_col].mean():.2f}%")
        print(f"Surge rate (overall): {valid[surge_col].mean()*100:.1f}%")

        # Correlation
        corr = valid[[score_col, ret_col]].corr().iloc[0, 1]
        print(f"Score vs return correlation: {corr:.3f}")

        # Quintile analysis
        valid = valid.copy()
        try:
            n_bins = min(5, valid[score_col].nunique())
            if n_bins < 2:
                print("Not enough score variation for quintile analysis.")
                continue
            labels = ["Q1 (low)", "Q2", "Q3", "Q4", "Q5 (high)"][:n_bins]
            valid["quintile"] = pd.qcut(valid[score_col], n_bins, labels=labels, duplicates='drop')
            quintile_stats = valid.groupby("quintile", observed=True).agg(
                avg_return=(ret_col, "mean"),
                surge_rate=(surge_col, "mean"),
                count=(ret_col, "count"),
            ).round(2)
            print(f"\nQuintile analysis ({horizon}):")
            print(quintile_stats.to_string())
        except ValueError:
            # Fall back to median split if qcut fails
            median = valid[score_col].median()
            valid["half"] = np.where(valid[score_col] >= median, "Top 50%", "Bottom 50%")
            half_stats = valid.groupby("half", observed=True).agg(
                avg_return=(ret_col, "mean"),
                surge_rate=(surge_col, "mean"),
                count=(ret_col, "count"),
            ).round(2)
            print(f"\nMedian split analysis ({horizon}):")
            print(half_stats.to_string())

    # --- Individual Signal Analysis ---
    signal_cols = [
        "price_change_score", "volume_change_score", "consistent_growth_score",
        "sustained_volume_growth_score", "consistent_monthly_growth_score",
        "trend_conflict_score", "rsi_score",
    ]

    for horizon, ret_col in [("7-day", "return_7d_pct"), ("30-day", "return_30d_pct")]:
        valid = df.dropna(subset=[ret_col])
        if valid.empty:
            continue

        print(f"\n--- Signal Correlations ({horizon}) ---")
        correlations = []
        for sig in signal_cols:
            if sig in valid.columns:
                corr = valid[[sig, ret_col]].corr().iloc[0, 1]
                # Also compute: avg return when signal > 0 vs signal == 0
                has_signal = valid[valid[sig] > 0]
                no_signal = valid[valid[sig] == 0]
                avg_with = has_signal[ret_col].mean() if len(has_signal) > 0 else 0
                avg_without = no_signal[ret_col].mean() if len(no_signal) > 0 else 0
                correlations.append({
                    "signal": sig,
                    "correlation": round(corr, 3),
                    "avg_return_with": round(avg_with, 2),
                    "avg_return_without": round(avg_without, 2),
                    "lift": round(avg_with - avg_without, 2),
                })

        corr_df = pd.DataFrame(correlations).sort_values("correlation", ascending=False)
        print(corr_df.to_string(index=False))

    # --- Peak Return vs Endpoint Return ---
    print("\n--- Peak vs Endpoint Analysis ---")
    for horizon, ret_col, peak_col in [("7d", "return_7d_pct", "peak_7d_pct"), ("30d", "return_30d_pct", "peak_30d_pct")]:
        valid = df.dropna(subset=[ret_col])
        if valid.empty or peak_col not in valid.columns:
            continue
        avg_endpoint = valid[ret_col].mean()
        avg_peak = valid[peak_col].mean()
        print(f"  {horizon}: avg endpoint return = {avg_endpoint:+.2f}%, avg peak return = {avg_peak:+.2f}% (missed {avg_peak - avg_endpoint:.2f}% by holding to endpoint)")

    # --- Volatility-Adjusted Surge Detection ---
    print("\n--- Volatility-Adjusted Surge Detection ---")
    for horizon, surge_col, thresh_col in [("7d", "surged_7d", "surge_threshold_7d"), ("30d", "surged_30d", "surge_threshold_30d")]:
        if surge_col in df.columns and thresh_col in df.columns:
            surge_rate = df[surge_col].mean() * 100
            avg_thresh = df[thresh_col].mean()
            surged = df[df[surge_col]]
            print(f"  {horizon}: {surge_rate:.1f}% of observations surged (avg threshold: {avg_thresh:.1f}%)")
            if not surged.empty:
                for sig in signal_cols:
                    if sig in surged.columns:
                        surged_avg = surged[sig].mean()
                        non_surged_avg = df[~df[surge_col]][sig].mean()
                        if surged_avg != non_surged_avg:
                            print(f"    {sig}: surged avg={surged_avg:.2f} vs non-surged avg={non_surged_avg:.2f}")

    # --- Pullback Analysis ---
    print("\n--- Pullback & Recovery Analysis ---")
    for horizon, pb_col, trough_col, ret_col in [
        ("7d", "pullback_7d", "trough_7d_pct", "return_7d_pct"),
        ("30d", "pullback_30d", "trough_30d_pct", "return_30d_pct"),
    ]:
        if pb_col in df.columns:
            pb_rate = df[pb_col].mean() * 100
            pullbacks = df[df[pb_col]]
            non_pullbacks = df[~df[pb_col]]
            print(f"  {horizon}: {pb_rate:.1f}% of observations had pullback-then-recovery")
            if not pullbacks.empty and ret_col in pullbacks.columns:
                print(f"    Avg endpoint return after pullback: {pullbacks[ret_col].mean():+.2f}%")
                print(f"    Avg endpoint return without pullback: {non_pullbacks[ret_col].mean():+.2f}%")
                print(f"    Avg trough (pullback cases): {pullbacks[trough_col].mean():+.2f}%")

    # --- Risk-Adjusted Returns ---
    print("\n--- Risk-Adjusted Returns (return / expected vol) ---")
    for horizon, ra_col in [("7d", "risk_adj_7d"), ("30d", "risk_adj_30d")]:
        valid = df.dropna(subset=[ra_col])
        if valid.empty:
            continue
        score_col_local = "backtestable_pct"
        corr = valid[[score_col_local, ra_col]].corr().iloc[0, 1]
        print(f"  {horizon}: score vs risk-adjusted return correlation = {corr:.3f}")
        top = valid.nlargest(int(len(valid) * 0.2), score_col_local)
        bottom = valid.nsmallest(int(len(valid) * 0.2), score_col_local)
        print(f"    Top 20% avg risk-adj return:    {top[ra_col].mean():+.3f}")
        print(f"    Bottom 20% avg risk-adj return: {bottom[ra_col].mean():+.3f}")

    # --- Weighted Score vs Equal-Weighted ---
    print("\n--- Weighted Score vs Equal-Weighted ---")
    for horizon, ret_col in [("7d", "return_7d_pct"), ("30d", "return_30d_pct")]:
        valid = df.dropna(subset=[ret_col])
        if valid.empty or "weighted_pct" not in valid.columns:
            continue
        corr_equal = valid[["backtestable_pct", ret_col]].corr().iloc[0, 1]
        corr_weighted = valid[["weighted_pct", ret_col]].corr().iloc[0, 1]
        print(f"  {horizon}: equal-weighted corr = {corr_equal:.3f}, evidence-weighted corr = {corr_weighted:.3f} ({'BETTER' if corr_weighted > corr_equal else 'WORSE'})")

        # Top 20% comparison
        top_equal = valid.nlargest(int(len(valid) * 0.2), "backtestable_pct")
        top_weighted = valid.nlargest(int(len(valid) * 0.2), "weighted_pct")
        print(f"    Top 20% (equal):    avg {horizon} return = {top_equal[ret_col].mean():+.2f}%")
        print(f"    Top 20% (weighted): avg {horizon} return = {top_weighted[ret_col].mean():+.2f}%")

    # --- Market Regime Analysis ---
    if "market_regime" in df.columns:
        print("\n--- Market Regime Analysis ---")
        for regime in df["market_regime"].unique():
            regime_df = df[df["market_regime"] == regime]
            if regime_df.empty:
                continue
            count = len(regime_df)
            for ret_col in ["return_7d_pct", "return_30d_pct"]:
                valid = regime_df.dropna(subset=[ret_col])
                if valid.empty:
                    continue
                avg_ret = valid[ret_col].mean()
                surge_rate = valid["surged_30d"].mean() * 100 if "surged_30d" in valid.columns else 0
                print(f"  {regime:>8s} ({count} obs): avg {ret_col.replace('return_', '').replace('_pct','')} return = {avg_ret:+.2f}%, surge rate = {surge_rate:.1f}%")

    # --- Exit Strategy Comparison ---
    print("\n--- Exit Strategy Comparison (30-day window) ---")
    exit_cols = {
        "return_hold": "Hold 30 days",
        "return_trailing_stop": "Trailing stop",
        "return_take_profit": "Take profit",
        "return_combined": "Combined (TP + SL)",
    }
    # Prefix handling: exit strategy results may have 'exit_' prefix
    for raw_col, label in list(exit_cols.items()):
        prefixed = f"exit_{raw_col}"
        if prefixed in df.columns:
            exit_cols[prefixed] = label
            if raw_col not in df.columns:
                del exit_cols[raw_col]

    available = {col: label for col, label in exit_cols.items() if col in df.columns}
    if available:
        print(f"  {'Strategy':<25s} {'Avg Return':>12s} {'Win Rate':>10s} {'Avg Win':>10s} {'Avg Loss':>10s}")
        print(f"  {'-'*25} {'-'*12} {'-'*10} {'-'*10} {'-'*10}")
        for col, label in available.items():
            valid = df.dropna(subset=[col])
            if valid.empty:
                continue
            avg = valid[col].mean()
            wins = valid[valid[col] > 0]
            losses = valid[valid[col] <= 0]
            win_rate = len(wins) / len(valid) * 100
            avg_win = wins[col].mean() if len(wins) > 0 else 0
            avg_loss = losses[col].mean() if len(losses) > 0 else 0
            print(f"  {label:<25s} {avg:>+11.2f}% {win_rate:>9.1f}% {avg_win:>+9.2f}% {avg_loss:>+9.2f}%")

        # Does weighted scoring improve exit strategy returns?
        if "weighted_pct" in df.columns:
            combined_col = next((c for c in ["exit_return_combined", "return_combined"] if c in df.columns), None)
            if combined_col:
                valid = df.dropna(subset=[combined_col, "weighted_pct"])
                if not valid.empty:
                    top_weighted = valid.nlargest(int(len(valid) * 0.2), "weighted_pct")
                    bottom_weighted = valid.nsmallest(int(len(valid) * 0.2), "weighted_pct")
                    print(f"\n  Combined strategy + weighted scoring:")
                    print(f"    Top 20% weighted coins:    avg return = {top_weighted[combined_col].mean():+.2f}%")
                    print(f"    Bottom 20% weighted coins: avg return = {bottom_weighted[combined_col].mean():+.2f}%")
                    spread = top_weighted[combined_col].mean() - bottom_weighted[combined_col].mean()
                    print(f"    Spread: {spread:+.2f}%")

    # --- Generate plots ---
    generate_backtest_plots(df, output_dir)

    # --- Summary verdict ---
    valid_7d = df.dropna(subset=["return_7d_pct"])
    if not valid_7d.empty:
        overall_corr = valid_7d[[score_col, "return_7d_pct"]].corr().iloc[0, 1]
        top_20 = valid_7d.nlargest(int(len(valid_7d) * 0.2), score_col)
        bottom_20 = valid_7d.nsmallest(int(len(valid_7d) * 0.2), score_col)

        print("\n" + "=" * 70)
        print("VERDICT")
        print("=" * 70)
        print(f"Score-return correlation (7d): {overall_corr:.3f}")
        print(f"Top 20% avg 7d return:    {top_20['return_7d_pct'].mean():+.2f}%")
        print(f"Bottom 20% avg 7d return: {bottom_20['return_7d_pct'].mean():+.2f}%")
        spread = top_20['return_7d_pct'].mean() - bottom_20['return_7d_pct'].mean()
        print(f"Spread (top - bottom):    {spread:+.2f}%")

        if spread > 2:
            print("\n>> POSITIVE: High-scoring coins outperform low-scoring coins.")
        elif spread > 0:
            print("\n>> WEAK: Slight edge but not statistically significant.")
        else:
            print("\n>> NEGATIVE: Scoring system does not predict returns.")

        # Identify best and worst signals
        valid_signals = df.dropna(subset=["return_7d_pct"])
        best_signal = None
        best_corr = -1
        worst_signal = None
        worst_corr = 1
        for sig in signal_cols:
            if sig in valid_signals.columns:
                c = valid_signals[[sig, "return_7d_pct"]].corr().iloc[0, 1]
                if not pd.isna(c):
                    if c > best_corr:
                        best_corr = c
                        best_signal = sig
                    if c < worst_corr:
                        worst_corr = c
                        worst_signal = sig

        if best_signal:
            print(f"\nBest signal:  {best_signal} (corr={best_corr:+.3f})")
        if worst_signal:
            print(f"Worst signal: {worst_signal} (corr={worst_corr:+.3f})")

    # Save analysis summary
    summary_path = os.path.join(output_dir, "backtest_summary.json")
    summary = {
        "date_range": f"{df['score_date'].min()} to {df['score_date'].max()}",
        "observations": len(df),
        "coins": int(df['coin_id'].nunique()),
    }
    if not valid_7d.empty:
        summary["correlation_7d"] = round(overall_corr, 3)
        summary["top_20_avg_return_7d"] = round(top_20['return_7d_pct'].mean(), 2)
        summary["bottom_20_avg_return_7d"] = round(bottom_20['return_7d_pct'].mean(), 2)
        summary["spread"] = round(spread, 2)

    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSummary saved to {summary_path}")


def generate_backtest_plots(df: pd.DataFrame, output_dir: str):
    """Generate backtest visualization plots."""
    score_col = "backtestable_pct"

    for horizon, ret_col, surge_col in [
        ("7d", "return_7d_pct", "surged_7d"),
        ("30d", "return_30d_pct", "surged_30d"),
    ]:
        valid = df.dropna(subset=[ret_col])
        if valid.empty:
            continue

        fig, axes = plt.subplots(1, 3, figsize=(18, 5))

        # 1. Scatter: score vs return
        ax = axes[0]
        ax.scatter(valid[score_col], valid[ret_col], alpha=0.3, s=10)
        z = np.polyfit(valid[score_col], valid[ret_col], 1)
        p = np.poly1d(z)
        x_line = np.linspace(valid[score_col].min(), valid[score_col].max(), 100)
        ax.plot(x_line, p(x_line), "r--", linewidth=2)
        ax.set_xlabel("Backtestable Score (%)")
        ax.set_ylabel(f"{horizon} Return (%)")
        ax.set_title(f"Score vs {horizon} Return")
        ax.axhline(y=0, color='grey', linestyle='-', alpha=0.3)

        # 2. Quintile/median bar chart
        ax = axes[1]
        valid_q = valid.copy()
        try:
            n_bins = min(5, valid_q[score_col].nunique())
            labels = ["Q1\n(low)", "Q2", "Q3", "Q4", "Q5\n(high)"][:n_bins]
            valid_q["bucket"] = pd.qcut(valid_q[score_col], n_bins, labels=labels, duplicates='drop')
        except ValueError:
            median = valid_q[score_col].median()
            valid_q["bucket"] = np.where(valid_q[score_col] >= median, "Top 50%", "Bottom 50%")
        q_means = valid_q.groupby("bucket", observed=True)[ret_col].mean()
        colors = ['#e74c3c' if v < 0 else '#2ecc71' for v in q_means.values]
        q_means.plot(kind='bar', ax=ax, color=colors)
        ax.set_xlabel("Score Bucket")
        ax.set_ylabel(f"Avg {horizon} Return (%)")
        ax.set_title(f"Return by Score Bucket ({horizon})")
        ax.axhline(y=0, color='grey', linestyle='-', alpha=0.3)
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=0)

        # 3. Signal correlation heatmap
        ax = axes[2]
        signal_cols = [
            "price_change_score", "volume_change_score", "consistent_growth_score",
            "sustained_volume_growth_score", "rsi_score", "trend_conflict_score",
        ]
        corrs = valid[signal_cols + [ret_col]].corr()[ret_col].drop(ret_col)
        colors = ['#2ecc71' if v > 0 else '#e74c3c' for v in corrs.values]
        corrs.plot(kind='barh', ax=ax, color=colors)
        ax.set_xlabel(f"Correlation with {horizon} return")
        ax.set_title(f"Signal Correlations ({horizon})")
        ax.axvline(x=0, color='grey', linestyle='-', alpha=0.3)

        plt.tight_layout()
        plot_path = os.path.join(output_dir, f"backtest_{horizon}.png")
        plt.savefig(plot_path, dpi=150)
        plt.close()
        print(f"Plot saved: {plot_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Crypto-Panda Backtester")
    parser.add_argument("--weeks", type=int, default=24, help="Number of weeks to backtest (default: 24)")
    parser.add_argument("--top-coins", type=int, default=50, help="Number of top coins to test (default: 50)")
    parser.add_argument("--universe", type=str, default="all", choices=["large", "mid", "small", "all"],
                        help="Coin universe: large (1-50), mid (51-200), small (201-1000), all (default: all)")
    parser.add_argument("--output", type=str, default=None, help="Output CSV path")
    args = parser.parse_args()

    run_backtest(weeks=args.weeks, top_n=args.top_coins, output_file=args.output, universe=args.universe)
