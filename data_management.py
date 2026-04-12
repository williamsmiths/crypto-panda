#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import glob
import logging
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List, Mapping, Optional, Tuple, Union

import pandas as pd
import psycopg2
from psycopg2 import OperationalError
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from config import LOG_DIR

# ============================
# Logging
# ============================

from logging_config import setup_logging

logger = setup_logging(__name__, caller_file=__file__)

# ----------------------------
# Database connection helper
# ----------------------------

@contextmanager
def get_aurora_connection():
    """Context manager for Aurora PostgreSQL connections."""
    conn = None
    try:
        conn = psycopg2.connect(
            host=os.getenv('AURORA_HOST'),
            database=os.getenv('AURORA_DB'),
            user=os.getenv('AURORA_USER'),
            password=os.getenv('AURORA_PASSWORD'),
            port=int(os.getenv('AURORA_PORT', '5432'))
        )
        yield conn
    finally:
        if conn is not None:
            conn.close()


def save_news_sentiment_history(coin_results: list) -> None:
    """
    Persist daily news sentiment data to Aurora for future backtesting.
    Over time this builds a dataset to validate news as a signal.
    """
    rows = []
    for r in coin_results:
        if r.get("news_article_count", 0) > 0:
            rows.append((
                r.get("coin_id", r.get("coin_name", "")),
                r.get("coin_name", ""),
                datetime.now(timezone.utc),
                r.get("raw_sentiment", 0),
                r.get("news_flag", "NO_DATA"),
                r.get("news_article_count", 0),
                r.get("news_velocity", "low"),
                ",".join(r.get("news_catalysts", [])),
                r.get("news_summary", "")[:500],
                r.get("news_key_risk", "")[:500],
                r.get("news_analysis_method", ""),
            ))

    if not rows:
        return

    try:
        with get_aurora_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS news_sentiment_history (
                        id SERIAL PRIMARY KEY,
                        coin_id VARCHAR(255) NOT NULL,
                        coin_name VARCHAR(255),
                        recorded_at TIMESTAMP DEFAULT NOW(),
                        sentiment FLOAT DEFAULT 0,
                        news_flag VARCHAR(20),
                        article_count INT DEFAULT 0,
                        velocity VARCHAR(20),
                        catalysts TEXT,
                        summary TEXT,
                        key_risk TEXT,
                        analysis_method VARCHAR(20),
                        UNIQUE (coin_id, recorded_at)
                    );
                """)
                cur.executemany("""
                    INSERT INTO news_sentiment_history
                    (coin_id, coin_name, recorded_at, sentiment, news_flag, article_count,
                     velocity, catalysts, summary, key_risk, analysis_method)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (coin_id, recorded_at) DO UPDATE SET sentiment = EXCLUDED.sentiment;
                """, rows)
                conn.commit()
                logger.info(f"Saved {len(rows)} news sentiment records to Aurora.")
    except Exception as e:
        logger.warning(f"Could not save news sentiment history: {e}")


# ----------------------------
# Helpers
# ----------------------------

def _utc_today_str() -> str:
    """YYYY-MM-DD (UTC)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def _ensure_dir(p: Union[str, Path]) -> None:
    Path(p).mkdir(parents=True, exist_ok=True)

# ----------------------------
# Tickers I/O
# ----------------------------

def load_tickers(file_path: str) -> Dict[str, str]:
    """
    Loads a CSV file containing coin names and tickers, and returns a dictionary mapping
    the coin names to their tickers.
    """
    df = pd.read_csv(file_path)
    tickers_dict = pd.Series(df['Ticker'].values, index=df['Name']).to_dict()
    logger.info(f"Loaded {len(tickers_dict)} tickers from {file_path}")
    return tickers_dict

# ----------------------------
# Results CSV (daily, UTC)
# ----------------------------

def save_result_to_csv(result: Mapping[str, object]) -> None:
    """
    Appends a single result as a row in a CSV file for the current UTC date.
    Creates the file with headers if it does not exist.
    """
    _ensure_dir(LOG_DIR)
    current_date = _utc_today_str()
    results_file = os.path.join(LOG_DIR, f"results_{current_date}.csv")

    try:
        exists = os.path.exists(results_file)
        pd.DataFrame([result]).to_csv(
            results_file,
            mode='a' if exists else 'w',
            header=not exists,
            index=False
        )
        logger.info(f"Wrote result row to {results_file}")
    except Exception as e:
        logger.error(f"Failed to write result to {results_file}: {e}")

def load_existing_results() -> pd.DataFrame:
    """
    Loads existing results from today's CSV (UTC).
    If today's file does not exist, deletes other 'results_*.csv' files in LOG_DIR and returns empty DataFrame.
    """
    def adjust_row_length(row, expected_columns=20):
        if len(row) < expected_columns:
            row += [None] * (expected_columns - len(row))
        return row

    current_date = _utc_today_str()
    results_file = os.path.join(LOG_DIR, f"results_{current_date}.csv")

    if not os.path.exists(results_file):
        logger.debug(f"File {results_file} does not exist. Removing all old results files in {LOG_DIR}.")
        try:
            for file in glob.glob(os.path.join(LOG_DIR, 'results_*.csv')):
                try:
                    os.remove(file)
                    logger.info(f"Deleted old results file: {file}")
                except Exception as e:
                    logger.error(f"Failed to delete file {file}: {e}")
        except Exception as e:
            logger.error(f"Error during cleanup in {LOG_DIR}: {e}")
        return pd.DataFrame()

    try:
        df = pd.read_csv(results_file, header=0, delimiter=',', engine='python', on_bad_lines='skip')
        expected_columns = len(df.columns)
        adjusted_rows = df.apply(lambda row: adjust_row_length(list(row), expected_columns), axis=1)
        adjusted_df = pd.DataFrame(adjusted_rows.tolist(), columns=df.columns)
        logger.info(f"Loaded {len(adjusted_df)} rows from {results_file}")
        return adjusted_df

    except FileNotFoundError:
        logger.error(f"File {results_file} not found after existence check.")
        return pd.DataFrame()
    except pd.errors.ParserError as e:
        logger.error(f"Error parsing {results_file}: {e}")
        return pd.DataFrame()
    except Exception as e:
        logger.error(f"Unexpected error reading {results_file}: {e}")
        return pd.DataFrame()

# ----------------------------
# Aurora (PostgreSQL) I/O
# ----------------------------

def retrieve_historical_data_from_aurora() -> pd.DataFrame:
    """
    Retrieves historical cumulative scores from Amazon Aurora for the past 2 months.
    """
    engine = None
    try:
        db_connection_str = (
            f"postgresql://{os.getenv('AURORA_USER')}:{os.getenv('AURORA_PASSWORD')}"
            f"@{os.getenv('AURORA_HOST')}:{os.getenv('AURORA_PORT', 5432)}/{os.getenv('AURORA_DB')}"
        )
        engine = create_engine(db_connection_str)
        query = """
            SELECT coin_name, cumulative_score, timestamp
            FROM coin_data
            WHERE timestamp >= NOW() - INTERVAL '2 months'
            ORDER BY timestamp;
        """
        df = pd.read_sql(query, engine)
        logger.info(f"Historical data (last 2 months) retrieved successfully: {len(df)} rows")
        return df

    except SQLAlchemyError as e:
        logger.error(f"Error retrieving historical data: {e}")
        return pd.DataFrame()
    except Exception as e:
        logger.error(f"Unexpected error retrieving historical data: {e}")
        return pd.DataFrame()
    finally:
        if engine:
            try:
                engine.dispose()
                logger.info("SQLAlchemy engine disposed.")
            except Exception as e:
                logger.error(f"Error disposing engine: {e}")

def save_cumulative_score_to_aurora(coin_id: str, coin_name: str, cumulative_score: float) -> None:
    """
    Save a cumulative score for a specific coin with a UTC date-based timestamp.
    """
    try:
        with get_aurora_connection() as conn:
            with conn.cursor() as cur:
                insert_query = """
                    INSERT INTO coin_data (coin_id, coin_name, cumulative_score, timestamp)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (coin_id, timestamp)
                    DO UPDATE SET cumulative_score = EXCLUDED.cumulative_score;
                """
                current_date = datetime.now(timezone.utc).date()
                cur.execute(insert_query, (coin_id, coin_name, cumulative_score, current_date))
                conn.commit()
                logger.info(f"Cumulative score saved/updated for {coin_name} on {current_date} (score={cumulative_score}).")
    except OperationalError as e:
        logger.error(f"Error connecting to Amazon Aurora DB: {e}")
    except Exception as e:
        logger.error(f"Error saving cumulative score for {coin_name}: {e}")

def save_cumulative_scores_batch(scores: list) -> None:
    """
    Batch save cumulative scores for multiple coins in a single DB connection.
    Each item in scores should be a tuple of (coin_id, coin_name, cumulative_score).
    """
    if not scores:
        return

    try:
        with get_aurora_connection() as conn:
            with conn.cursor() as cur:
                insert_query = """
                    INSERT INTO coin_data (coin_id, coin_name, cumulative_score, timestamp)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (coin_id, timestamp)
                    DO UPDATE SET cumulative_score = EXCLUDED.cumulative_score;
                """
                current_date = datetime.now(timezone.utc).date()
                rows = [(cid, cname, cscore, current_date) for cid, cname, cscore in scores]
                cur.executemany(insert_query, rows)
                conn.commit()
                logger.info(f"Batch saved {len(rows)} cumulative scores to Aurora.")
    except OperationalError as e:
        logger.error(f"Error connecting to Amazon Aurora DB (batch save): {e}")
    except Exception as e:
        logger.error(f"Error batch saving cumulative scores: {e}")


def save_detailed_scores_batch(results: list) -> None:
    """
    Batch save detailed sub-scores for backtesting analysis.
    Each item in results should be the full result dict from analyze_coin.
    """
    if not results:
        return

    try:
        with get_aurora_connection() as conn:
            with conn.cursor() as cur:
                insert_query = """
                    INSERT INTO coin_scores_detailed (
                        coin_id, coin_name, score_date,
                        price_change_score, volume_change_score, tweet_score,
                        consistent_growth_score, sustained_volume_growth_score,
                        fear_and_greed_score, event_score, sentiment_score,
                        surge_score, digest_score, trending_score,
                        consistent_monthly_growth_score, trend_conflict_score,
                        rsi_score, cumulative_score, cumulative_score_percentage,
                        liquidity_risk, market_cap, volume_24h
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (coin_id, score_date)
                    DO UPDATE SET cumulative_score = EXCLUDED.cumulative_score,
                                  cumulative_score_percentage = EXCLUDED.cumulative_score_percentage;
                """
                current_ts = datetime.now(timezone.utc)
                rows = []
                for r in results:
                    rows.append((
                        r.get("coin_id"), r.get("coin_name"), current_ts,
                        r.get("price_change_score", 0), r.get("volume_change_score", 0),
                        min(1.0, r.get("tweets", 0) / 10.0) if r.get("tweets", 0) else 0,
                        1 if r.get("consistent_growth") == "Yes" else 0,
                        1 if r.get("sustained_volume_growth") == "Yes" else 0,
                        r.get("fear_and_greed_score", 0) if isinstance(r.get("fear_and_greed_score"), (int, float)) else 0,
                        1 if r.get("events", 0) > 0 else 0,
                        r.get("sentiment_score", 0),
                        r.get("trending_score", 0),
                        1 if r.get("consistent_monthly_growth") == "Yes" else 0,
                        1 if r.get("trend_conflict") == "Yes" else 0,
                        r.get("rsi_score", 0),
                        r.get("cumulative_score", 0), r.get("cumulative_score_percentage", 0),
                        r.get("liquidity_risk", "Unknown"),
                        r.get("market_cap", 0), r.get("volume_24h", 0),
                    ))
                cur.executemany(insert_query, rows)
                conn.commit()
                logger.info(f"Batch saved {len(rows)} detailed score records.")
    except OperationalError as e:
        logger.error(f"Error saving detailed scores: {e}")
    except Exception as e:
        logger.error(f"Error batch saving detailed scores: {e}")


def create_coin_data_table_if_not_exists() -> None:
    """
    Creates the 'coin_data' table in Amazon Aurora (PostgreSQL) if it doesn't already exist,
    storing time series data for cumulative scores.
    """
    try:
        with get_aurora_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS coin_data (
                        id SERIAL PRIMARY KEY,
                        coin_id VARCHAR(255) NOT NULL,
                        coin_name VARCHAR(255) NOT NULL,
                        cumulative_score FLOAT NOT NULL,
                        timestamp TIMESTAMP DEFAULT NOW(),
                        UNIQUE (coin_id, timestamp)
                    );
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS coin_scores_detailed (
                        id SERIAL PRIMARY KEY,
                        coin_id VARCHAR(255) NOT NULL,
                        coin_name VARCHAR(255) NOT NULL,
                        score_date TIMESTAMP DEFAULT NOW(),
                        price_change_score FLOAT DEFAULT 0,
                        volume_change_score FLOAT DEFAULT 0,
                        tweet_score FLOAT DEFAULT 0,
                        consistent_growth_score FLOAT DEFAULT 0,
                        sustained_volume_growth_score FLOAT DEFAULT 0,
                        fear_and_greed_score FLOAT DEFAULT 0,
                        event_score FLOAT DEFAULT 0,
                        sentiment_score FLOAT DEFAULT 0,
                        surge_score FLOAT DEFAULT 0,
                        digest_score FLOAT DEFAULT 0,
                        trending_score FLOAT DEFAULT 0,
                        consistent_monthly_growth_score FLOAT DEFAULT 0,
                        trend_conflict_score FLOAT DEFAULT 0,
                        rsi_score FLOAT DEFAULT 0,
                        cumulative_score FLOAT DEFAULT 0,
                        cumulative_score_percentage FLOAT DEFAULT 0,
                        liquidity_risk VARCHAR(20) DEFAULT 'Unknown',
                        market_cap BIGINT DEFAULT 0,
                        volume_24h BIGINT DEFAULT 0,
                        UNIQUE (coin_id, score_date)
                    );
                """)
                conn.commit()
                logger.info("Tables 'coin_data' and 'coin_scores_detailed' created or already exist.")
    except OperationalError as e:
        logger.error(f"Error while connecting to Amazon Aurora: {e}")
    except Exception as e:
        logger.error(f"Error creating tables: {e}")