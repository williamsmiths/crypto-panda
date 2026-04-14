#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import json
import pandas as pd
import logging
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from tqdm import tqdm
import traceback
from collections import defaultdict
import matplotlib.pyplot as plt
import seaborn as sns  # kept for correlation heatmap
from pathlib import Path
from typing import Union

from api_clients import (
    call_with_retries,
    filter_active_and_ranked_coins
)
from coin_analysis import analyze_coin
from data_management import (
    save_result_to_csv,
    retrieve_historical_data_from_aurora,
    save_cumulative_score_to_aurora,
    save_cumulative_scores_batch,
    save_detailed_scores_batch,
    create_coin_data_table_if_not_exists,
    load_existing_results,
    load_tickers,
)
from plotting import plot_top_coins_over_time
from report_generation import (
    gpt4o_summarize_each_coin,
    save_report_to_excel,
    generate_html_report_with_recommendations,
    send_email_with_report,
)
from backtesting import run_backtesting, generate_backtesting_html
from config import (
    TEST_ONLY,
    CUMULATIVE_SCORE_REPORTING_THRESHOLD,
    NUMBER_OF_TOP_COINS_TO_MONITOR,
    CRYPTO_NEWS_TICKERS,
    LOG_DIR,
    COIN_PAPRIKA_API_KEY,
    FEAR_GREED_THRESHOLD,
    MAX_WORKERS,
    COIN_TIMEOUT,
)
from sqlalchemy import create_engine

from coinpaprika import client as Coinpaprika

# ============================
# Logging
# ============================

from logging_config import setup_logging

# Instantiate module logger
logger = setup_logging(__name__, log_dir=LOG_DIR, caller_file=__file__)

# ----------------------------
# Setup
# ----------------------------

# Ensure log directory exists for any artifacts
Path(LOG_DIR).mkdir(parents=True, exist_ok=True)

# CoinPaprika client (only used here for coins list)
client = Coinpaprika.Client(api_key=COIN_PAPRIKA_API_KEY)

coin_audit_log: list = []


def utc_today_iso() -> str:
    """Current date in UTC, YYYY-MM-DD."""
    return datetime.now(timezone.utc).date().isoformat()


def process_single_coin(
    coin: dict,
    existing_results: pd.DataFrame,
    all_tickers: dict,
    end_date: str,
):
    """
    Processes a single coin. Returns (result_dict, audit_entry) or None.
    Thread-safe: no shared mutable state.
    """
    try:
        coin_id = coin["id"]
        coin_name = str(coin["name"]).lower()

        if existing_results is not None and not existing_results.empty and coin_id in existing_results.get("coin_id", pd.Series([])).values:
            logger.debug(f"Skipping already processed coin: {coin_id}")
            return None

        logger.debug(f"Processing {coin_name} ({coin_id})")

        result = analyze_coin(
            coin_id,
            coin_name,
            end_date,
            ticker_data=all_tickers.get(coin_id, {}),
        )

        save_result_to_csv(result)

        audit_entry = {
            "coin_id": coin_id,
            "coin_name": coin_name,
            "ticker": coins_dict.get(coin_name),
            "date": datetime.now(timezone.utc).isoformat(),
            "included_in_report": None,
            "reason_for_exclusion": None,
            "scores": {
                "price_change_score": result.get("price_change_score"),
                "volume_change_score": result.get("volume_change_score"),
                "sentiment_score": result.get("sentiment_score"),
                "fear_and_greed_index": result.get("fear_and_greed_index"),
                "trending_score": result.get("trending_score"),
                "consistent_monthly_growth": result.get("consistent_monthly_growth"),
                "trend_conflict": result.get("trend_conflict"),
                "cumulative_score": result.get("cumulative_score"),
                "cumulative_score_percentage": result.get("cumulative_score_percentage"),
                "liquidity_risk": result.get("liquidity_risk", "Unknown"),
            },
        }

        return (result, audit_entry)

    except Exception as e:
        logger.error(f"Error processing {coin.get('name')} ({coin.get('id')}): {e}")
        logger.error(traceback.format_exc())
        return None


def _collect_score_usage(result: dict, score_usage: defaultdict):
    """Aggregate a single result into score_usage. Called from main thread only."""
    score_usage["price_change_score"].append(int(result.get("price_change_score", 0) or 0))
    score_usage["volume_change_score"].append(int(result.get("volume_change_score", 0) or 0))
    score_usage["sentiment_score"].append(int(result.get("sentiment_score", 0) or 0))
    score_usage["consistent_growth"].append(1 if result.get("consistent_growth", "No") == "Yes" else 0)
    score_usage["sustained_volume_growth"].append(1 if result.get("sustained_volume_growth", "No") == "Yes" else 0)

    try:
        fear_greed_value = int(result.get("fear_and_greed_index", 0) or 0)
        score_usage["fear_and_greed_index"].append(1 if fear_greed_value > FEAR_GREED_THRESHOLD else 0)
    except (ValueError, TypeError, KeyError):
        score_usage["fear_and_greed_index"].append(0)


    score_usage["trending_score"].append(float(result.get("trending_score", 0) or 0))
    score_usage["consistent_monthly_growth"].append(1 if result.get("consistent_monthly_growth", "No") == "Yes" else 0)
    score_usage["trend_conflict"].append(1 if result.get("trend_conflict", "No") == "Yes" else 0)
    score_usage["cumulative_score"].append(int(result.get("cumulative_score", 0) or 0))
    score_usage["cumulative_score_percentage"].append(float(result.get("cumulative_score_percentage", 0) or 0))


def summarize_scores(score_usage: defaultdict, output_dir: str = "../logs/"):
    """
    Generates a summary + histograms + correlation heatmap for score_usage.
    """
    os.makedirs(output_dir, exist_ok=True)
    summary_file = os.path.join(output_dir, "score_summary.txt")

    with open(summary_file, "w") as f:
        f.write("--- SCORING SUMMARY ---\n\n")
        for score_type, scores in score_usage.items():
            s = pd.Series(scores, dtype="float")
            summary = (
                f"{score_type}:\n"
                f"  Count: {len(s)}\n"
                f"  Mean: {s.mean():.2f}\n"
                f"  Std Dev: {s.std():.2f}\n"
                f"  Min: {s.min()}, Max: {s.max()}\n"
                f"  Non-zero count: {(s > 0).sum()} ({(s > 0).mean()*100:.2f}%)\n\n"
            )
            print(summary)
            f.write(summary)

            # Histogram
            plt.figure()
            s.hist(bins=10)
            plt.title(score_type)
            plt.xlabel("Score")
            plt.ylabel("Frequency")
            plt.grid(True)
            plt.tight_layout()
            plt.savefig(os.path.join(output_dir, f"{score_type}_histogram.png"))
            plt.close()

    # Correlation heatmap (if enough data)
    df_scores = pd.DataFrame(score_usage)
    if df_scores.shape[0] >= 2 and df_scores.shape[1] >= 2:
        corr = df_scores.corr(numeric_only=True)
        plt.figure(figsize=(10, 8))
        sns.heatmap(corr, annot=True, cmap="coolwarm", fmt=".2f")
        plt.title("Correlation between scoring components")
        plt.tight_layout()
        plt.savefig(os.path.join(output_dir, "score_correlation_heatmap.png"))
        plt.close()
    else:
        logger.debug("Not enough data to compute correlation heatmap.")


def monitor_coins_and_send_report():
    """
    Main entry point for monitoring coins and generating a weekly report.
    """
    create_coin_data_table_if_not_exists()

    if TEST_ONLY:
        existing_results = pd.DataFrame([])
        coins_to_monitor = [
            {"id": "btc-bitcoin", "name": "Bitcoin"},
            {"id": "eth-ethereum", "name": "Ethereum"},
        ]
    else:
        existing_results = load_existing_results()
        try:
            # Use call_with_retries instead of the old api_call_with_retries
            coins_to_monitor = call_with_retries(client.coins)
        except Exception as e:
            logger.error(f"Failed to fetch coins list from CoinPaprika: {e}")
            coins_to_monitor = []

        logger.debug(f"Number of coins retrieved: {len(coins_to_monitor)}")
        coins_to_monitor = filter_active_and_ranked_coins(
            coins_to_monitor, NUMBER_OF_TOP_COINS_TO_MONITOR
        )

    logger.debug(f"Number of active and ranked coins selected: {len(coins_to_monitor)}")
    end_date = utc_today_iso()

    tickers_dict = load_tickers(CRYPTO_NEWS_TICKERS)



    # Market regime detection via BTC price
    try:
        from api_clients import fetch_historical_ticker_data
        btc_start = (datetime.now(timezone.utc) - timedelta(days=210)).date().isoformat()
        btc_df = fetch_historical_ticker_data("btc-bitcoin", btc_start, end_date)
        if btc_df is not None and not btc_df.empty and len(btc_df) >= 200:
            ma50 = btc_df['price'].rolling(50).mean().iloc[-1]
            ma200 = btc_df['price'].rolling(200).mean().iloc[-1]
            btc_price = btc_df['price'].iloc[-1]
            if btc_price > ma50 and ma50 > ma200:
                market_regime = "bull"
            elif btc_price < ma50 and ma50 < ma200:
                market_regime = "bear"
            else:
                market_regime = "sideways"
        else:
            market_regime = "unknown"
    except Exception as e:
        logger.warning(f"Could not determine market regime: {e}")
        market_regime = "unknown"

    logger.info(f"Market regime: {market_regime}")
    if market_regime in ("bear", "sideways"):
        logger.warning(f"Market regime is {market_regime}. Scoring accuracy is reduced in non-bull markets. Report will include regime warning.")

    # Fetch all tickers in bulk (1 API call) for ticker features
    try:
        all_tickers = {t['id']: t for t in call_with_retries(client.tickers)}
        logger.info(f"Fetched {len(all_tickers)} tickers for ticker features")
    except Exception:
        logger.warning("Could not fetch bulk tickers for features")
        all_tickers = {}

    score_usage: defaultdict = defaultdict(list)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_coin = {
            executor.submit(
                process_single_coin,
                c,
                existing_results,
                all_tickers,
                end_date,
            ): c
            for c in coins_to_monitor
        }
        results_list = []
        for future in tqdm(as_completed(future_to_coin), total=len(future_to_coin), desc="Processing Coins"):
            try:
                output = future.result(timeout=COIN_TIMEOUT)
                if output is not None:
                    result, audit_entry = output
                    results_list.append(result)
                    coin_audit_log.append(audit_entry)
                    _collect_score_usage(result, score_usage)
            except FuturesTimeoutError:
                coin = future_to_coin[future]
                logger.error(f"Timeout processing {coin.get('name')} ({coin.get('id')})")
            except Exception as e:
                coin = future_to_coin[future]
                logger.error(f"Unhandled error for {coin.get('name')} ({coin.get('id')}): {e}")

    # Batch save all cumulative scores to Aurora in a single connection
    aurora_scores = [
        (r["coin_id"], r["coin_name"], r["cumulative_score_percentage"])
        for r in results_list
    ]
    save_cumulative_scores_batch(aurora_scores)
    save_detailed_scores_batch(results_list)

    if not results_list:
        logger.debug("No coin results produced; exiting after score summary.")
        summarize_scores(score_usage, output_dir=LOG_DIR)
        return

    df = pd.DataFrame(results_list)
    raw_df = df.copy()

    try:
        if not df.empty:
            # Filter for report
            df = df[
                (df["liquidity_risk"].isin(["Low", "Medium"]))
                & (df["cumulative_score_percentage"] > CUMULATIVE_SCORE_REPORTING_THRESHOLD)
            ]

            logger.debug("DataFrame is not empty, processing report entries.")
            coins_in_df = df["coin_name"].unique()

            # Plot top coins over time if we have history
            if len(coins_in_df) > 0:
                historical_data = retrieve_historical_data_from_aurora()
                if not historical_data.empty:
                    plot_top_coins_over_time(
                        historical_data[historical_data["coin_name"].isin(coins_in_df)],
                        top_n=10,
                    )

            report_entries = df.to_dict("records")
            report_entries = sorted(report_entries, key=lambda x: x.get("cumulative_score", 0), reverse=True)
            logger.debug(f"Report entries after sorting: {len(report_entries)} entries")

            # Stage 2: Fetch news (Google News RSS, free) for shortlisted coins only
            if report_entries:
                from coin_analysis import apply_news_confirmation
                logger.info(f"Stage 2: Fetching news for {len(report_entries)} shortlisted coins via Google News RSS...")
                for entry in report_entries:
                    apply_news_confirmation(entry, entry["coin_name"])
                logger.info(f"News sentiment applied. Flags: {[e.get('news_flag', 'N/A') for e in report_entries[:5]]}")

            # Ensure numeric fields are correctly typed
            numeric_fields = [
                "price_change_score", "volume_change_score", "sentiment_score",
                "trending_score",
                "cumulative_score",
                "cumulative_score_percentage", "fear_and_greed_index", "market_cap",
                "volume_24h", "events",
            ]
            for field in numeric_fields:
                if field in df.columns:
                    df[field] = pd.to_numeric(df[field], errors="coerce")

            logger.debug("DataFrame contents before GPT-4o recommendations:\n%s", df.to_string())

            gpt_recommendations = gpt4o_summarize_each_coin(df)
            logger.debug("GPT-4o recommendations generated.")

            # --- Backtesting ---
            backtesting_html = ""
            try:
                db_connection_str = (
                    f"postgresql://{os.getenv('AURORA_USER')}:{os.getenv('AURORA_PASSWORD')}"
                    f"@{os.getenv('AURORA_HOST')}:{os.getenv('AURORA_PORT', 5432)}/{os.getenv('AURORA_DB')}"
                )
                bt_engine = create_engine(db_connection_str)
                backtest_results = run_backtesting(bt_engine)
                backtesting_html = generate_backtesting_html(backtest_results)
                bt_engine.dispose()
                logger.info("Backtesting report generated.")
            except Exception as e:
                logger.error(f"Backtesting failed (non-fatal): {e}")

            html_report = generate_html_report_with_recommendations(report_entries, None, gpt_recommendations, market_regime=market_regime, backtesting_html=backtesting_html)
            logger.debug("HTML report generated successfully.")

            attachment_path = save_report_to_excel(report_entries)
            logger.debug(f"Report saved to Excel at: {attachment_path}")

            send_email_with_report(
                html_report,
                attachment_path,
                recommendations=gpt_recommendations.get("recommendations"),
            )
            logger.debug("Email sent successfully.")

            current_date = utc_today_iso()
            results_file = os.path.join(LOG_DIR, f"results_{current_date}.csv")

            if os.path.exists(results_file):
                try:
                    archive_dir = os.path.join(LOG_DIR, "processed")
                    os.makedirs(archive_dir, exist_ok=True)
                    archived_path = os.path.join(archive_dir, os.path.basename(results_file))
                    os.rename(results_file, archived_path)
                    logger.debug(f"{results_file} archived to {archived_path}.")
                except Exception as e:
                    logger.debug(f"Failed to archive {results_file}: {e}")

            summarize_scores(score_usage, output_dir=LOG_DIR)

            # Build audit flags
            raw_coin_ids = set(raw_df["coin_id"])
            final_coin_ids = set(df["coin_id"])
            already_processed_ids = set(existing_results["coin_id"]) if (existing_results is not None and not existing_results.empty and "coin_id" in existing_results.columns) else set()

            for entry in coin_audit_log:
                cid = entry["coin_id"]
                if cid in final_coin_ids:
                    entry["included_in_report"] = True
                    entry["reason_for_exclusion"] = None
                elif cid in raw_coin_ids:
                    entry["included_in_report"] = False
                    entry["reason_for_exclusion"] = "Filtered due to low score or liquidity"
                elif cid in already_processed_ids:
                    entry["included_in_report"] = False
                    entry["reason_for_exclusion"] = "Skipped (already processed)"
                else:
                    entry["included_in_report"] = False
                    entry["reason_for_exclusion"] = "Processing failed"

            audit_log_file = os.path.join(LOG_DIR, f"audit_log_{utc_today_iso()}.json")
            with open(audit_log_file, "w") as f:
                json.dump(coin_audit_log, f, indent=2)

            audit_df = pd.json_normalize(coin_audit_log)
            audit_df.to_csv(os.path.join(LOG_DIR, f"audit_log_{utc_today_iso()}.csv"), index=False)

        else:
            logger.debug("No valid entries to report. DataFrame is empty.")
            summarize_scores(score_usage, output_dir=LOG_DIR)

    except Exception as e:
        logger.error(f"An error occurred during the report generation process: {e}")
        logger.debug(traceback.format_exc())


if __name__ == "__main__":
    monitor_coins_and_send_report()
