#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import logging
from pathlib import Path
from typing import Union

import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from config import LOG_DIR

# ============================
# Logging
# ============================

from logging_config import setup_logging

logger = setup_logging(__name__, caller_file=__file__)

# ----------------------------
# Plotting
# ----------------------------

def plot_top_coins_over_time(
    historical_data: pd.DataFrame,
    top_n: int = 5,
    file_name: str = os.path.join(LOG_DIR, "top_coins_plot.png"),
    window: int = 5,
) -> None:
    """
    Plots the cumulative scores of the top coins over time with optional smoothing and saves the plot to a file.
    """
    try:
        Path(LOG_DIR).mkdir(parents=True, exist_ok=True)

        # Ensure timestamp is datetime
        historical_data = historical_data.copy()
        historical_data.loc[:, 'timestamp'] = pd.to_datetime(historical_data['timestamp'])

        # Calculate average cumulative score and select top N
        top_coins = historical_data.groupby('coin_name')['cumulative_score'].mean().nlargest(top_n).index
        logger.info(f"Plotting top {len(top_coins)} coins: {list(top_coins)}")

        # Filter data
        top_data = historical_data[historical_data['coin_name'].isin(top_coins)]

        plt.figure(figsize=(10, 6))
        for coin in top_coins:
            coin_data = top_data[top_data['coin_name'] == coin].sort_values('timestamp')
            coin_data['smoothed_score'] = coin_data['cumulative_score'].rolling(window=window, min_periods=1).mean()
            plt.plot(coin_data['timestamp'], coin_data['smoothed_score'], label=coin, marker='o')

        # Format x-axis
        ax = plt.gca()
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))

        # Labels and legend
        plt.title(f"Top {top_n} Coins by Cumulative Score Over Time")
        plt.xlabel("Date")
        plt.ylabel("Cumulative Score")
        plt.legend()

        # Save
        plt.tight_layout()
        plt.savefig(file_name)
        logger.info(f"Plot saved → {file_name}")

    except Exception as e:
        logger.error(f"Error plotting top coins over time: {e}")