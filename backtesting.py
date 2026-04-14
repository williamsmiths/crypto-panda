#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Daily backtesting report.

Compares past coin recommendations (from Aurora) against actual price
performance using CoinPaprika historical data. Produces an HTML section
that can be embedded in the daily email report.
"""

import os
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

import pandas as pd

from api_clients import fetch_historical_ticker_data, call_with_retries
from config import CUMULATIVE_SCORE_REPORTING_THRESHOLD, LOG_DIR

# ============================
# Logging
# ============================

def setup_logging(name: str,
                  log_dir: Union[str, Path] = None,
                  level: str = None) -> logging.Logger:
    base_dir = Path(__file__).resolve().parent
    log_dir = Path(log_dir or (base_dir / "../logs")).resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{Path(__file__).stem}.log"
    level_name = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    level_val = getattr(logging, level_name, logging.INFO)
    logger = logging.getLogger(name)
    logger.setLevel(level_val)
    logger.propagate = False
    for h in list(logger.handlers):
        logger.removeHandler(h)
    fmt = "%(asctime)sZ [%(levelname)s] %(name)s | %(message)s"
    datefmt = "%Y-%m-%dT%H:%M:%S"
    formatter = logging.Formatter(fmt=fmt, datefmt=datefmt)
    ch = logging.StreamHandler()
    ch.setLevel(level_val)
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    fh = logging.FileHandler(str(log_path), mode="w", encoding="utf-8", delay=False)
    fh.setLevel(level_val)
    fh.setFormatter(formatter)
    logger.addHandler(fh)
    logger.info(f"Logging started → {log_path} (level={level_name})")
    return logger

logger = setup_logging(__name__)

# ============================
# Backtesting lookback windows
# ============================

LOOKBACK_WINDOWS = [
    {"label": "7-Day", "days": 7},
    {"label": "14-Day", "days": 14},
    {"label": "30-Day", "days": 30},
]


def _fetch_price_on_date(coin_id: str, target_date: str) -> Optional[float]:
    """
    Fetch the closing price for a coin on a specific date via CoinPaprika.
    Returns None if data is unavailable.
    """
    try:
        end = (datetime.strptime(target_date, "%Y-%m-%d") + timedelta(days=2)).strftime("%Y-%m-%d")
        df = fetch_historical_ticker_data(coin_id, target_date, end)
        if df.empty:
            return None
        df["date"] = pd.to_datetime(df["date"])
        target_dt = pd.Timestamp(target_date)
        exact = df[df["date"] == target_dt]
        if not exact.empty:
            return float(exact.iloc[0]["price"])
        return float(df.iloc[0]["price"])
    except Exception as e:
        logger.debug(f"Price fetch failed for {coin_id} on {target_date}: {e}")
        return None


def _fetch_current_price(coin_id: str) -> Optional[float]:
    """
    Fetch the most recent price for a coin.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
    try:
        df = fetch_historical_ticker_data(coin_id, yesterday, today)
        if df.empty:
            return None
        return float(df.iloc[-1]["price"])
    except Exception as e:
        logger.debug(f"Current price fetch failed for {coin_id}: {e}")
        return None


def retrieve_past_recommendations(engine, lookback_days: int, score_threshold: float) -> pd.DataFrame:
    """
    Query Aurora for coins that scored above the threshold within the lookback window.
    Returns DataFrame with columns: coin_id, coin_name, cumulative_score, timestamp.
    """
    try:
        query = f"""
            SELECT coin_id, coin_name, cumulative_score, timestamp
            FROM coin_data
            WHERE timestamp >= NOW() - INTERVAL '{lookback_days} days'
              AND cumulative_score >= {score_threshold}
            ORDER BY timestamp DESC, cumulative_score DESC;
        """
        df = pd.read_sql(query, engine)
        logger.info(f"Retrieved {len(df)} past recommendations (lookback={lookback_days}d, threshold={score_threshold})")
        return df
    except Exception as e:
        logger.error(f"Failed to retrieve past recommendations: {e}")
        return pd.DataFrame()


def run_backtesting(engine) -> Dict:
    """
    Run backtesting across multiple lookback windows.

    Returns a dict with structure:
    {
        "windows": [
            {
                "label": "7-Day",
                "days": 7,
                "total_recommendations": int,
                "profitable_count": int,
                "hit_rate": float,
                "avg_return_pct": float,
                "best_performer": {"coin": str, "return_pct": float},
                "worst_performer": {"coin": str, "return_pct": float},
                "details": [
                    {
                        "coin_id": str,
                        "coin_name": str,
                        "recommendation_date": str,
                        "score_at_recommendation": float,
                        "price_at_recommendation": float,
                        "current_price": float,
                        "return_pct": float,
                    },
                    ...
                ]
            },
            ...
        ]
    }
    """
    results = {"windows": []}

    for window in LOOKBACK_WINDOWS:
        label = window["label"]
        days = window["days"]
        logger.info(f"Running backtesting for {label} window ({days} days)")

        past_recs = retrieve_past_recommendations(engine, days, CUMULATIVE_SCORE_REPORTING_THRESHOLD)
        if past_recs.empty:
            results["windows"].append({
                "label": label,
                "days": days,
                "total_recommendations": 0,
                "profitable_count": 0,
                "hit_rate": 0.0,
                "avg_return_pct": 0.0,
                "best_performer": None,
                "worst_performer": None,
                "details": [],
            })
            continue

        # Deduplicate: take the earliest recommendation per coin
        past_recs["timestamp"] = pd.to_datetime(past_recs["timestamp"])
        earliest_recs = past_recs.sort_values("timestamp").drop_duplicates(subset=["coin_id"], keep="first")

        details = []
        for _, row in earliest_recs.iterrows():
            coin_id = row["coin_id"]
            coin_name = row["coin_name"]
            rec_date = row["timestamp"].strftime("%Y-%m-%d")
            score = float(row["cumulative_score"])

            rec_price = _fetch_price_on_date(coin_id, rec_date)
            cur_price = _fetch_current_price(coin_id)

            if rec_price is None or cur_price is None or rec_price == 0:
                logger.debug(f"Skipping {coin_name}: rec_price={rec_price}, cur_price={cur_price}")
                continue

            return_pct = ((cur_price - rec_price) / rec_price) * 100

            details.append({
                "coin_id": coin_id,
                "coin_name": coin_name,
                "recommendation_date": rec_date,
                "score_at_recommendation": score,
                "price_at_recommendation": rec_price,
                "current_price": cur_price,
                "return_pct": round(return_pct, 2),
            })

        if not details:
            results["windows"].append({
                "label": label,
                "days": days,
                "total_recommendations": 0,
                "profitable_count": 0,
                "hit_rate": 0.0,
                "avg_return_pct": 0.0,
                "best_performer": None,
                "worst_performer": None,
                "details": [],
            })
            continue

        # Sort by return
        details.sort(key=lambda x: x["return_pct"], reverse=True)
        profitable = [d for d in details if d["return_pct"] > 0]
        total = len(details)
        hit_rate = (len(profitable) / total * 100) if total > 0 else 0.0
        avg_return = sum(d["return_pct"] for d in details) / total if total > 0 else 0.0

        results["windows"].append({
            "label": label,
            "days": days,
            "total_recommendations": total,
            "profitable_count": len(profitable),
            "hit_rate": round(hit_rate, 1),
            "avg_return_pct": round(avg_return, 2),
            "best_performer": {
                "coin": details[0]["coin_name"],
                "return_pct": details[0]["return_pct"],
            },
            "worst_performer": {
                "coin": details[-1]["coin_name"],
                "return_pct": details[-1]["return_pct"],
            },
            "details": details,
        })

    return results


def generate_backtesting_html(backtest_results: Dict) -> str:
    """
    Generate an HTML section for the backtesting report to embed in the email.
    """
    if not backtest_results or not backtest_results.get("windows"):
        return ""

    # Summary cards for each window
    summary_cards = ""
    for window in backtest_results["windows"]:
        if window["total_recommendations"] == 0:
            summary_cards += f"""
            <tr>
                <td style="padding:8px 12px;border:1px solid #ddd;font-size:14px;">{window['label']}</td>
                <td colspan="4" style="padding:8px 12px;border:1px solid #ddd;font-size:14px;color:#999;">No recommendations in this period</td>
            </tr>
            """
            continue

        hit_color = "#27ae60" if window["hit_rate"] >= 50 else "#e74c3c"
        avg_color = "#27ae60" if window["avg_return_pct"] >= 0 else "#e74c3c"

        summary_cards += f"""
        <tr>
            <td style="padding:8px 12px;border:1px solid #ddd;font-size:14px;font-weight:bold;">{window['label']}</td>
            <td style="padding:8px 12px;border:1px solid #ddd;font-size:14px;text-align:center;">{window['total_recommendations']}</td>
            <td style="padding:8px 12px;border:1px solid #ddd;font-size:14px;text-align:center;color:{hit_color};font-weight:bold;">{window['hit_rate']}%</td>
            <td style="padding:8px 12px;border:1px solid #ddd;font-size:14px;text-align:center;color:{avg_color};font-weight:bold;">{window['avg_return_pct']:+.2f}%</td>
            <td style="padding:8px 12px;border:1px solid #ddd;font-size:14px;text-align:center;">
                {window['profitable_count']}/{window['total_recommendations']}
            </td>
        </tr>
        """

    # Detailed breakdown - show top 10 for each window with data
    detail_sections = ""
    for window in backtest_results["windows"]:
        if not window["details"]:
            continue

        top_details = window["details"][:10]
        detail_rows = ""
        for d in top_details:
            ret_color = "#27ae60" if d["return_pct"] >= 0 else "#e74c3c"
            ret_arrow = "&#9650;" if d["return_pct"] >= 0 else "&#9660;"
            coin_name_display = d["coin_name"].title()
            coin_url = f"https://coinpaprika.com/coin/{d['coin_id']}/"

            detail_rows += f"""
            <tr>
                <td style="padding:6px 10px;border:1px solid #eee;font-size:13px;">
                    <a href="{coin_url}" target="_blank" style="color:#0077cc;text-decoration:none;">{coin_name_display}</a>
                </td>
                <td style="padding:6px 10px;border:1px solid #eee;font-size:13px;text-align:center;">{d['recommendation_date']}</td>
                <td style="padding:6px 10px;border:1px solid #eee;font-size:13px;text-align:center;">{d['score_at_recommendation']:.0f}%</td>
                <td style="padding:6px 10px;border:1px solid #eee;font-size:13px;text-align:right;">${d['price_at_recommendation']:,.6f}</td>
                <td style="padding:6px 10px;border:1px solid #eee;font-size:13px;text-align:right;">${d['current_price']:,.6f}</td>
                <td style="padding:6px 10px;border:1px solid #eee;font-size:13px;text-align:right;color:{ret_color};font-weight:bold;">
                    {ret_arrow} {d['return_pct']:+.2f}%
                </td>
            </tr>
            """

        best = window.get("best_performer")
        worst = window.get("worst_performer")
        highlights = ""
        if best:
            highlights += f'<span style="color:#27ae60;">Best: {best["coin"].title()} ({best["return_pct"]:+.2f}%)</span>'
        if worst:
            highlights += f' &nbsp;|&nbsp; <span style="color:#e74c3c;">Worst: {worst["coin"].title()} ({worst["return_pct"]:+.2f}%)</span>'

        detail_sections += f"""
        <tr>
            <td colspan="6" style="padding:12px 10px 4px;font-size:15px;font-weight:bold;color:#264653;border:none;">
                {window['label']} Details {f'&mdash; {highlights}' if highlights else ''}
            </td>
        </tr>
        <tr>
            <td style="padding:6px 10px;border:1px solid #ddd;font-size:12px;font-weight:bold;background:#f0f0f0;">Coin</td>
            <td style="padding:6px 10px;border:1px solid #ddd;font-size:12px;font-weight:bold;background:#f0f0f0;text-align:center;">Rec. Date</td>
            <td style="padding:6px 10px;border:1px solid #ddd;font-size:12px;font-weight:bold;background:#f0f0f0;text-align:center;">Score</td>
            <td style="padding:6px 10px;border:1px solid #ddd;font-size:12px;font-weight:bold;background:#f0f0f0;text-align:right;">Rec. Price</td>
            <td style="padding:6px 10px;border:1px solid #ddd;font-size:12px;font-weight:bold;background:#f0f0f0;text-align:right;">Current</td>
            <td style="padding:6px 10px;border:1px solid #ddd;font-size:12px;font-weight:bold;background:#f0f0f0;text-align:right;">Return</td>
        </tr>
        {detail_rows}
        """

    html = f"""
    <table width="100%" cellpadding="0" cellspacing="0" border="0" style="background-color:#fff;">
        <tr>
            <td style="padding:20px;">
                <h3 style="font-size:20px;color:#2a9d8f;margin-bottom:5px;">Daily Backtesting Report</h3>
                <p style="font-size:13px;color:#777;margin-top:0;margin-bottom:15px;">
                    Performance of past recommendations vs. actual price movement
                </p>

                <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;margin-bottom:20px;">
                    <tr style="background-color:#264653;">
                        <td style="padding:8px 12px;font-size:13px;font-weight:bold;color:#fff;border:1px solid #ddd;">Window</td>
                        <td style="padding:8px 12px;font-size:13px;font-weight:bold;color:#fff;border:1px solid #ddd;text-align:center;">Coins Tracked</td>
                        <td style="padding:8px 12px;font-size:13px;font-weight:bold;color:#fff;border:1px solid #ddd;text-align:center;">Hit Rate</td>
                        <td style="padding:8px 12px;font-size:13px;font-weight:bold;color:#fff;border:1px solid #ddd;text-align:center;">Avg Return</td>
                        <td style="padding:8px 12px;font-size:13px;font-weight:bold;color:#fff;border:1px solid #ddd;text-align:center;">Profitable</td>
                    </tr>
                    {summary_cards}
                </table>

                <table width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;">
                    {detail_sections}
                </table>
            </td>
        </tr>
    </table>
    """
    return html
