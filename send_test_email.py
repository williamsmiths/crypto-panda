#!/usr/bin/env python3
"""
Send a test email with a sample Crypto-Panda report using mock data.
No paid APIs required — only SMTP credentials.

Usage:
    python send_test_email.py

Required env vars in .env:
    EMAIL_FROM, EMAIL_TO, SMTP_SERVER, SMTP_USERNAME, SMTP_PASSWORD
"""

import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from config import EMAIL_FROM, EMAIL_TO, SMTP_SERVER, SMTP_USERNAME, SMTP_PASSWORD, LOG_DIR
from report_generation import generate_html_report_with_recommendations, send_email_with_report, save_report_to_excel
from pathlib import Path


def generate_mock_plot(output_path):
    """Generate a sample cumulative score plot with mock historical data."""
    np.random.seed(42)
    dates = pd.date_range(end=pd.Timestamp.now(), periods=60, freq='D')

    coins = {
        'Solana': 65 + np.cumsum(np.random.normal(0.4, 2, 60)),
        'Bitcoin': 55 + np.cumsum(np.random.normal(0.3, 1.5, 60)),
        'Ethereum': 45 + np.cumsum(np.random.normal(0.2, 2, 60)),
        'Avalanche': 40 + np.cumsum(np.random.normal(0.1, 2.5, 60)),
        'Chainlink': 35 + np.cumsum(np.random.normal(0.15, 1.8, 60)),
    }

    fig, ax = plt.subplots(figsize=(10, 5))
    for name, scores in coins.items():
        scores = np.clip(scores, 0, 100)
        ax.plot(dates, scores, label=name, linewidth=2)

    ax.set_title("Top Coins by Cumulative Score Over Time", fontsize=14)
    ax.set_xlabel("Date")
    ax.set_ylabel("Cumulative Score (%)")
    ax.legend(loc='upper left')
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%b %d'))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=2))
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.savefig(output_path, dpi=150)
    plt.close()
    print(f"Plot saved to: {output_path}")


def main():
    # Check SMTP config
    missing = []
    if not EMAIL_FROM: missing.append("EMAIL_FROM")
    if not EMAIL_TO: missing.append("EMAIL_TO")
    if not SMTP_SERVER: missing.append("SMTP_SERVER")
    if not SMTP_USERNAME: missing.append("SMTP_USERNAME")
    if not SMTP_PASSWORD: missing.append("SMTP_PASSWORD")

    if missing:
        print(f"ERROR: Missing env vars: {', '.join(missing)}")
        print("Set these in your .env file (see .env.example)")
        sys.exit(1)

    print(f"Sending test email from {EMAIL_FROM} to {EMAIL_TO} via {SMTP_SERVER}...")

    # Mock report entries (sample coins with realistic scores)
    report_entries = [
        {
            "coin_id": "btc-bitcoin",
            "coin_name": "Bitcoin",
            "market_cap": 1_350_000_000_000,
            "volume_24h": 28_500_000_000,
            "price_change_score": 3,
            "volume_change_score": 2,
            "tweets": 8,
            "consistent_growth": "Yes",
            "sustained_volume_growth": "Yes",
            "fear_and_greed_index": 72,
            "events": 3,
            "sentiment_score": 0.78,
            "surging_keywords_score": 1,
            "news_digest_score": 1,
            "trending_score": 1.8,
            "liquidity_risk": "Low",
            "rsi_score": 0.0,
            "rsi_explanation": "RSI=62 (neutral)",
            "cumulative_score": 16.1,
            "cumulative_score_percentage": 76.67,
            "explanation": "Bitcoin (btc-bitcoin) analysis: Strong momentum across all timeframes...",
            "coin_news": [{"title": "Bitcoin breaks $100k resistance level"}],
            "trend_conflict": "No",
        },
        {
            "coin_id": "eth-ethereum",
            "coin_name": "Ethereum",
            "market_cap": 420_000_000_000,
            "volume_24h": 15_200_000_000,
            "price_change_score": 2,
            "volume_change_score": 2,
            "tweets": 5,
            "consistent_growth": "Yes",
            "sustained_volume_growth": "No",
            "fear_and_greed_index": 72,
            "events": 1,
            "sentiment_score": 0.65,
            "surging_keywords_score": 1,
            "news_digest_score": 1,
            "trending_score": 1.5,
            "liquidity_risk": "Low",
            "rsi_score": 1.0,
            "rsi_explanation": "RSI=28 (oversold, potential bounce)",
            "cumulative_score": 13.65,
            "cumulative_score_percentage": 65.0,
            "explanation": "Ethereum (eth-ethereum) analysis: Oversold with strong fundamentals...",
            "coin_news": [{"title": "Ethereum staking hits new ATH"}],
            "trend_conflict": "No",
        },
        {
            "coin_id": "sol-solana",
            "coin_name": "Solana",
            "market_cap": 78_000_000_000,
            "volume_24h": 3_100_000_000,
            "price_change_score": 3,
            "volume_change_score": 3,
            "tweets": 12,
            "consistent_growth": "Yes",
            "sustained_volume_growth": "Yes",
            "fear_and_greed_index": 72,
            "events": 2,
            "sentiment_score": 0.82,
            "surging_keywords_score": 1,
            "news_digest_score": 0,
            "trending_score": 2.0,
            "liquidity_risk": "Low",
            "rsi_score": 1.0,
            "rsi_explanation": "RSI=75 (strong momentum with volume confirmation)",
            "cumulative_score": 18.32,
            "cumulative_score_percentage": 87.24,
            "explanation": "Solana (sol-solana) analysis: Exceptional momentum with RSI confirmation...",
            "coin_news": [{"title": "Solana TVL surpasses $12B milestone"}],
            "trend_conflict": "No",
        },
    ]

    # Mock digest summary
    digest_summary = {
        "surge_summary": [
            "Bitcoin momentum continues as institutional inflows hit record levels",
            "Solana ecosystem growth accelerates with new DeFi protocols launching",
            "Ethereum staking yields attract renewed interest amid market recovery",
        ],
        "tickers": ["BTC", "ETH", "SOL", "AVAX", "LINK"],
    }

    # Mock GPT recommendations
    gpt_recommendations = {
        "recommendations": [
            {
                "coin": "Bitcoin",
                "coin_id": "btc-bitcoin",
                "recommendation": "Yes",
                "reason": "Strong momentum across all timeframes with institutional accumulation. RSI neutral at 62 with room to run. Santiment signals show net exchange outflows and whale buying. Cumulative score of 76.67% is well above threshold.",
            },
            {
                "coin": "Ethereum",
                "coin_id": "eth-ethereum",
                "recommendation": "Yes",
                "reason": "Oversold at RSI 28 with strong fundamentals intact. Dev activity remains high and staking growth is accelerating. This looks like a classic mean-reversion setup with 65% cumulative score.",
            },
            {
                "coin": "Solana",
                "coin_id": "sol-solana",
                "recommendation": "Yes",
                "reason": "Highest scorer at 87.24% with momentum confirmed by RSI 75 and volume. All on-chain metrics firing: exchange outflows, whale accumulation, and dev activity. Strong breakout candidate.",
            },
        ]
    }

    # Generate HTML report
    html_report = generate_html_report_with_recommendations(
        report_entries, digest_summary, gpt_recommendations
    )

    # Save Excel attachment and generate plot
    Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
    attachment_path = save_report_to_excel(report_entries)
    print(f"Excel report saved to: {attachment_path}")

    plot_path = os.path.join(LOG_DIR, 'top_coins_plot.png')
    generate_mock_plot(plot_path)

    # Send the email with plot
    send_email_with_report(
        html_report,
        attachment_path,
        plot_image_path=plot_path,
        recommendations=gpt_recommendations.get("recommendations"),
    )

    print("Test email sent! Check your inbox.")


if __name__ == "__main__":
    main()
