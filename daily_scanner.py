#!/usr/bin/env python3
"""
Crypto-Panda Daily Scanner

Lightweight daily scan with configurable coin universe (small/mid/large).
Uses CoinPaprika ticker data for real-time signals + historical for RSI.

Usage:
    python daily_scanner.py --universe small --top-coins 200
    python daily_scanner.py --universe large --top-coins 50
    python daily_scanner.py --universe all --top-coins 300
"""

import sys
import os
import argparse
import smtplib
import html as html_mod
import time
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from logging_config import setup_logging
from config import (
    EMAIL_FROM, EMAIL_TO, SMTP_SERVER, SMTP_USERNAME, SMTP_PASSWORD, SMTP_PORT,
    COIN_PAPRIKA_API_KEY, LOG_DIR,
)
from api_clients import (
    call_with_retries,
    fetch_historical_ticker_data,
    fetch_fear_and_greed_index,
)
from coin_analysis import compute_rsi, compute_rsi_score, classify_market_cap, classify_liquidity_risk
from coin_universe import get_universe_config, RANK_RANGES, EXCLUDED_COINS, classify_universe
from features import extract_ticker_features
from coinpaprika import client as Coinpaprika

logger = setup_logging("daily_scanner", caller_file=__file__)


def detect_market_regime_from_btc(end_date: str) -> str:
    """Detect bull/bear/sideways from BTC 50/200 MA."""
    try:
        start = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=210)).strftime("%Y-%m-%d")
        df = fetch_historical_ticker_data("btc-bitcoin", start, end_date)
        if df is None or df.empty or len(df) < 200:
            return "unknown"
        ma50 = df['price'].rolling(50).mean().iloc[-1]
        ma200 = df['price'].rolling(200).mean().iloc[-1]
        price = df['price'].iloc[-1]
        if price > ma50 and ma50 > ma200:
            return "bull"
        elif price < ma50 and ma50 < ma200:
            return "bear"
        return "sideways"
    except Exception as e:
        logger.warning(f"Regime detection failed: {e}")
        return "unknown"


def scan_coin(coin_id: str, end_date: str, ticker_data: dict, universe_config: dict) -> dict:
    """
    Scan a single coin using historical data + live ticker features.
    Applies universe-specific weights and exit targets.
    """
    try:
        start_90d = (datetime.strptime(end_date, "%Y-%m-%d") - timedelta(days=90)).strftime("%Y-%m-%d")
        df = fetch_historical_ticker_data(coin_id, start_90d, end_date)

        if df is None or df.empty or len(df) < 14:
            return None

        price = float(df['price'].iloc[-1])
        market_cap = int(df['market_cap'].iloc[-1]) if 'market_cap' in df.columns else 0
        volume_24h = int(df['volume_24h'].iloc[-1]) if 'volume_24h' in df.columns else 0

        if price == 0 or market_cap == 0:
            return None

        # Liquidity check
        cap_class = classify_market_cap(market_cap)
        liquidity = classify_liquidity_risk(volume_24h, cap_class)
        if liquidity == "High":
            return None

        # RSI
        rsi = compute_rsi(df['price'])
        rsi_score, rsi_expl = compute_rsi_score(df['price'])

        # Price changes from historical
        price_7d = float(df['price'].iloc[-7]) if len(df) >= 7 else price
        price_30d = float(df['price'].iloc[-30]) if len(df) >= 30 else price
        change_7d = ((price - price_7d) / price_7d * 100) if price_7d > 0 else 0
        change_30d = ((price - price_30d) / price_30d * 100) if price_30d > 0 else 0

        # Weekly growth consistency (best small-cap signal)
        if len(df) >= 7:
            last_7 = df.tail(7)
            up_days_7 = (last_7['price'].diff() > 0).sum()
            consistent_growth = up_days_7 >= 4
        else:
            consistent_growth = False
            up_days_7 = 0

        # Monthly growth consistency
        if len(df) >= 30:
            up_days_30 = (df.tail(30)['price'].diff() > 0).sum()
            monthly_growth = up_days_30 >= 18
        else:
            monthly_growth = False
            up_days_30 = 0

        # Sustained volume growth
        if len(df) >= 7:
            vol_up_days = (df.tail(7)['volume_24h'].diff() > 0).sum()
            sustained_volume = vol_up_days >= 4
        else:
            sustained_volume = False

        # Volatility for exit targets
        vol_daily = df['price'].pct_change().std()
        if vol_daily is None or vol_daily != vol_daily:
            vol_daily = 0.03

        # Extract CoinPaprika ticker features (live data)
        ticker_features = extract_ticker_features(ticker_data) if ticker_data else {}

        # Universe-specific exit targets
        exit_cfg = universe_config["exit_targets"]
        take_profit = round(max(exit_cfg["min_take_profit"], vol_daily * 100 * exit_cfg["take_profit_multiplier"]), 1)
        stop_loss = round(max(exit_cfg["min_stop_loss"], vol_daily * 100 * exit_cfg["stop_loss_multiplier"]), 1)

        # Compute weighted score using universe-specific weights
        weights = universe_config["weights"]
        score_components = {
            "rsi": rsi_score,
            "consistent_growth": 1.0 if consistent_growth else 0.0,
            "consistent_monthly_growth": 1.0 if monthly_growth else 0.0,
            "sustained_volume_growth": 1.0 if sustained_volume else 0.0,
            "price_change": min(1.0, max(0.0, change_7d / 30.0)),
            "volume_change": min(1.0, max(0.0, (ticker_features.get("volume_24h_change_pct") or 0) / 100.0)),
            "volume_spike_24h": ticker_features.get("volume_spike_24h_score", 0),
            "distance_from_ath": ticker_features.get("distance_from_ath_score", 0),
            "multi_timeframe_momentum": ticker_features.get("multi_timeframe_momentum_score", 0),
            # Signals not available in stage 1 daily scan
            "fear_and_greed": 0, "trend_conflict": 0,
        }

        weighted_score = sum(weights.get(k, 0) * v for k, v in score_components.items())
        weighted_max = sum(abs(w) for w in weights.values())
        weighted_pct = round((weighted_score / weighted_max) * 100, 1) if weighted_max else 0

        return {
            "coin_id": coin_id,
            "price": price,
            "market_cap": market_cap,
            "volume_24h": volume_24h,
            "rank": ticker_data.get("rank", 0) if ticker_data else 0,
            "rsi": round(rsi, 1),
            "rsi_score": rsi_score,
            "rsi_explanation": rsi_expl,
            "change_1h": ticker_features.get("change_1h"),
            "change_6h": ticker_features.get("change_6h"),
            "change_24h": ticker_features.get("change_24h"),
            "change_7d": round(change_7d, 2),
            "change_30d": round(change_30d, 2),
            "consistent_growth": consistent_growth,
            "up_days_7": up_days_7,
            "monthly_growth": monthly_growth,
            "sustained_volume": sustained_volume,
            "volume_spike": ticker_features.get("volume_spike_24h_score", 0),
            "volume_spike_expl": ticker_features.get("volume_spike_expl", ""),
            "distance_from_ath": ticker_features.get("percent_from_ath"),
            "distance_ath_score": ticker_features.get("distance_from_ath_score", 0),
            "mtf_score": ticker_features.get("multi_timeframe_momentum_score", 0),
            "mtf_expl": ticker_features.get("mtf_expl", ""),
            "liquidity": liquidity,
            "weighted_pct": weighted_pct,
            "take_profit_pct": take_profit,
            "stop_loss_pct": stop_loss,
        }
    except Exception as e:
        logger.debug(f"Error scanning {coin_id}: {e}")
        return None


def generate_llm_commentary(top_alerts: list, regime: str, fng: int) -> str:
    """Generate natural language commentary for the top coins using LLM."""
    try:
        from report_generation import llm_chat_completion
    except Exception:
        return ""

    if not top_alerts:
        return ""

    coins_data = []
    for a in top_alerts:
        coins_data.append(
            f"- {a['coin_id']} (rank #{a.get('rank','?')}): "
            f"RSI={a['rsi']}, 7d={a['change_7d']:+.1f}%, "
            f"growth={a.get('up_days_7',0)}/7 days green, "
            f"volume spike={a.get('volume_spike',0):.1f}, "
            f"ATH distance={a.get('distance_from_ath', 'N/A')}%, "
            f"score={a['weighted_pct']:.0f}%, "
            f"TP=+{a['take_profit_pct']}%, SL=-{a['stop_loss_pct']}%"
        )

    prompt = f"""You are a crypto market analyst writing a daily briefing email. Be concise and direct.
Write in plain text — no markdown, no asterisks, no bullet points. Use simple line breaks between coins.

Market conditions: regime={regime}, Fear & Greed Index={fng}.

For each coin below, write exactly one paragraph (2-3 sentences) covering:
1. The key signal (why it triggered — mention specific numbers)
2. Your verdict: BUY, WATCH, or AVOID (write the word in capitals)
3. The main risk and the trailing stop level

Rules:
- RSI > 70: verdict is WATCH or AVOID (overbought)
- RSI < 30: highlight oversold bounce potential, lean toward BUY
- 7d change > +50%: verdict is AVOID (already pumped)
- Volume spike + consistent growth = strongest BUY setup
- Always state the trailing stop (SL) percentage
- Start each paragraph with the coin name in capitals

End with one sentence summarising the overall market outlook.

Coins:
{chr(10).join(coins_data)}"""

    try:
        logger.info("Generating LLM commentary for top coins...")
        content = llm_chat_completion(prompt, temperature=0.3)
        return content.strip()
    except Exception as e:
        logger.warning(f"LLM commentary failed: {e}")
        return ""


def _build_coin_table(alerts: list, universe_label: str) -> str:
    """Build an HTML table for a single universe's alerts."""
    if not alerts:
        return ""

    rows = ""
    for a in alerts:
        flags = ""
        if a.get('rsi', 50) < 30: flags += "🔥"
        if a.get('consistent_growth'): flags += "📈"
        if a.get('volume_spike', 0) >= 0.7: flags += "💥"
        if a.get('distance_ath_score', 0) >= 0.6: flags += "🏷️"

        coin_name = html_mod.escape(str(a['coin_id']))
        ath_txt = f"{a.get('distance_from_ath', 0):.0f}%" if a.get('distance_from_ath') else ""

        rows += f"""
        <tr style="border-bottom:1px solid #eee;">
            <td style="padding:6px 8px;"><b>{coin_name}</b> {flags}</td>
            <td style="padding:6px 8px;text-align:right;">#{a.get('rank', '?')}</td>
            <td style="padding:6px 8px;text-align:right;">${a['price']:,.4f}</td>
            <td style="padding:6px 8px;text-align:right;">{a['rsi']}</td>
            <td style="padding:6px 8px;text-align:right;">{a.get('change_1h', 0) or 0:+.1f}%</td>
            <td style="padding:6px 8px;text-align:right;">{a.get('change_24h', 0) or 0:+.1f}%</td>
            <td style="padding:6px 8px;text-align:right;">{a['change_7d']:+.1f}%</td>
            <td style="padding:6px 8px;text-align:right;">{a.get('up_days_7', 0)}/7</td>
            <td style="padding:6px 8px;text-align:right;">{ath_txt}</td>
            <td style="padding:6px 8px;text-align:right;font-weight:bold;">{a['weighted_pct']:.0f}%</td>
            <td style="padding:6px 8px;text-align:right;color:green;">+{a['take_profit_pct']}%</td>
            <td style="padding:6px 8px;text-align:right;color:red;">-{a['stop_loss_pct']}%</td>
        </tr>"""

    universe_colors = {"large": "#264653", "mid": "#2a9d8f", "small": "#e76f51"}
    header_color = universe_colors.get(universe_label, "#264653")

    return f"""
    <h3 style="color:{header_color};margin:20px 0 5px 0;font-size:16px;">{universe_label.upper()} CAP ({len(alerts)} coins)</h3>
    <table style="width:100%;border-collapse:collapse;background:#fff;font-size:12px;margin-bottom:15px;">
        <tr style="background:{header_color};color:white;">
            <th style="padding:6px 8px;text-align:left;">Coin</th>
            <th style="padding:6px 8px;text-align:right;">Rank</th>
            <th style="padding:6px 8px;text-align:right;">Price</th>
            <th style="padding:6px 8px;text-align:right;">RSI</th>
            <th style="padding:6px 8px;text-align:right;">1h</th>
            <th style="padding:6px 8px;text-align:right;">24h</th>
            <th style="padding:6px 8px;text-align:right;">7d</th>
            <th style="padding:6px 8px;text-align:right;">Growth</th>
            <th style="padding:6px 8px;text-align:right;">ATH</th>
            <th style="padding:6px 8px;text-align:right;">Score</th>
            <th style="padding:6px 8px;text-align:right;">TP</th>
            <th style="padding:6px 8px;text-align:right;">SL</th>
        </tr>
        {rows}
    </table>"""


def send_alert_email(alerts_by_universe, regime: str, fng: int, universe: str, llm_commentary: str = ""):
    """Send alert email with guide, per-universe tables, and LLM commentary.

    alerts_by_universe: dict of {universe_name: [alerts]} OR list (legacy single-universe)
    """
    if not EMAIL_FROM or not EMAIL_TO or not SMTP_SERVER:
        logger.error("SMTP not configured. Skipping alert email.")
        return

    # Handle legacy single-universe list format
    if isinstance(alerts_by_universe, list):
        alerts_by_universe = {universe: alerts_by_universe}

    total_coins = sum(len(v) for v in alerts_by_universe.values())

    regime_emoji = {"bull": "🟢", "bear": "🔴", "sideways": "🟡"}.get(regime, "⚪")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Build tables for each universe
    tables_html = ""
    for u in ["large", "mid", "small"]:
        if u in alerts_by_universe and alerts_by_universe[u]:
            tables_html += _build_coin_table(alerts_by_universe[u], u)

    # LLM commentary section
    import re as _re
    commentary_html = ""
    if llm_commentary:
        # Convert markdown bold **text** to HTML <b>text</b>, then escape the rest
        formatted = html_mod.escape(llm_commentary)
        # Restore bold: escaped ** becomes &ast;&ast; or just ** after escape — handle both
        formatted = _re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', formatted)
        # Convert markdown-style labels
        formatted = formatted.replace('BUY', '<span style="color:#27ae60;font-weight:bold;">BUY</span>')
        formatted = formatted.replace('WATCH', '<span style="color:#f39c12;font-weight:bold;">WATCH</span>')
        formatted = formatted.replace('AVOID', '<span style="color:#e74c3c;font-weight:bold;">AVOID</span>')
        formatted = formatted.replace('\n', '<br>')
        commentary_html = f"""
        <div style="background:#f0f7ff;border-left:4px solid #264653;padding:15px;margin:15px 0;font-size:13px;line-height:1.7;">
            <h3 style="margin:0 0 10px 0;color:#264653;font-size:15px;">AI Analysis</h3>
            {formatted}
        </div>"""

    # Regime explanation
    regime_explanations = {
        "bull": "BTC is above its 50-day and 200-day moving averages. Uptrend in progress. Signals tend to be more reliable.",
        "bear": "BTC is below both moving averages. Downtrend. Be extra cautious, use tighter stops, and consider smaller positions.",
        "sideways": "BTC is between its moving averages. No clear trend. Signals are less reliable. Wait for confirmation before acting.",
        "unknown": "Not enough data to determine the trend. Proceed with caution.",
    }
    fng_explanation = ""
    if fng is not None:
        if fng <= 25:
            fng_explanation = "Extreme Fear — the market is scared. Historically, this is when oversold bounces work best (buy when others are fearful)."
        elif fng <= 45:
            fng_explanation = "Fear — market is cautious. Look for quality setups with volume confirmation."
        elif fng <= 55:
            fng_explanation = "Neutral — no strong emotion either way."
        elif fng <= 75:
            fng_explanation = "Greed — market is confident. Be careful not to chase pumps."
        else:
            fng_explanation = "Extreme Greed — market is euphoric. High risk of reversal. Tighten stops."

    universes_in_report = ", ".join(u.upper() for u in alerts_by_universe.keys())

    html = f"""
    <html><body style="font-family:Arial,sans-serif;color:#333;margin:0;padding:20px;background:#f9f9f9;">
        <h2 style="color:#264653;">Crypto-Panda Daily Alert</h2>

        <!-- Market conditions explained -->
        <div style="background:#fff;border:1px solid #ddd;padding:12px 15px;margin:10px 0;font-size:13px;line-height:1.6;">
            <b>Market Conditions ({now})</b><br>
            {regime_emoji} <b>Market Regime: {regime.upper()}</b> — {regime_explanations.get(regime, '')}<br>
            <b>Fear &amp; Greed Index: {fng if fng else 'N/A'}</b> — {fng_explanation}
        </div>

        <!-- How to read this report -->
        <div style="background:#fff;border:1px solid #ddd;padding:15px;margin:10px 0;font-size:13px;line-height:1.7;">
            <b style="font-size:15px;">How to read this report</b><br><br>

            <b style="font-size:14px;">What the flags mean:</b><br>
            🔥 <b>RSI&lt;30 (Oversold)</b> — The coin has been beaten down more than usual. Historically, oversold coins tend to bounce back. This is a strong short-term buy signal, especially if other flags agree.<br>
            📈 <b>Weekly Growth</b> — The price went up on 4 or more of the last 7 days. This shows a consistent uptrend is forming — not just a one-day spike. Our backtesting found this is the single best predictor for small-cap coins.<br>
            💥 <b>Volume Spike</b> — Trading volume (the amount of money being traded) jumped by 50% or more in the last 24 hours. This means money is flowing into this coin — something is happening.<br>
            🏷️ <b>ATH Discount</b> — The coin is currently 50-85% below its all-time high (the highest price it ever reached). If the project behind the coin is still active, this means there is significant room for the price to recover.<br><br>

            <b style="font-size:14px;">What each column means:</b><br><br>

            <b>RSI</b> (Relative Strength Index)<br>
            A number from 0 to 100 that measures whether a coin is overbought or oversold.
            <b>Below 30</b> = oversold (the coin has dropped a lot — potential buy opportunity).
            <b>Above 70</b> = overbought (the coin has risen a lot — risky to buy now, it may pull back).
            <b>30-70</b> = neutral.
            Example: RSI 25 means the coin is beaten down and likely to bounce. RSI 80 means it's pumped too far too fast.<br><br>

            <b>1h / 24h / 7d</b> (Price Changes)<br>
            How much the price changed over the last 1 hour, 24 hours, and 7 days.
            If all three are positive (green), momentum is strong across all timeframes.
            Example: +2.1% / +5.3% / +12.0% = coin is trending up consistently.<br><br>

            <b>Growth</b> (Green Days)<br>
            How many of the last 7 days the price closed higher than the day before.
            4/7 or higher means the coin has been consistently going up, not just spiking randomly.
            This is the single strongest signal for small-cap coins in our backtesting (+2.31% weekly lift).<br><br>

            <b>ATH</b> (All-Time High Distance)<br>
            How far the current price is below the coin's highest-ever price.
            Example: -70% means the coin once traded at 3.3x today's price. If the project is still alive, that's room to recover.
            Sweet spot: -50% to -85% with volume confirmation = recovery play.<br><br>

            <b>Score</b> (Weighted Composite)<br>
            Our composite score combining all signals, weighted by what actually predicted returns in 4 years of backtesting.
            Different weights for large-cap vs small-cap coins.
            <b>40%+ = strong</b> (multiple signals agree). Below 30% = weak.<br><br>

            <b>TP</b> (Take Profit)<br>
            Your sell target. When the price rises this much above your buy price, consider selling some or all to lock in the profit.
            This is calculated based on each coin's historical volatility — volatile coins get wider targets, stable coins get tighter ones.
            Example: TP +15% means if you buy at $1.00, consider selling at $1.15.<br><br>

            <b>SL</b> (Stop Loss / Trailing Stop)<br>
            Your safety net. If the price drops this much <i>from its highest point since you bought</i>, sell to protect your money.
            The key word is "trailing" — this stop moves UP as the price rises, but never moves down.
            Example: You buy at $1.00 with SL -8%. Price rises to $1.30 (your stop is now at $1.20, which is 8% below $1.30).
            If the price then drops to $1.20, you sell — locking in a +20% profit instead of waiting for it to crash back to $0.80.<br><br>

            <b style="color:#c0392b;font-size:14px;">Quick decision rules:</b><br>
            ✅ <b>BUY</b> if: RSI below 50 + Score above 40% + has 📈 or 💥 flag<br>
            ⚠️ <b>WATCH</b> if: RSI between 50-70, or coin is missing volume confirmation<br>
            ❌ <b>AVOID</b> if: RSI above 70 (overbought) or 7d change above +50% (the surge already happened)
        </div>

        {commentary_html}

        <p><b>{total_coins} buy-worthy coin(s) across {universes_in_report}.</b></p>

        {tables_html}

        <p style="font-size:10px;color:#999;margin-top:20px;">
            <b>DISCLAIMER:</b> This is NOT financial advice. Crypto-Panda is an educational research tool.
            Backtesting shows a small edge but does not guarantee future returns.
            Never invest money you cannot afford to lose. Always DYOR.
            See full disclaimer at github.com/sjmoran/crypto-panda
        </p>
    </body></html>
    """

    msg = MIMEMultipart()
    msg['Subject'] = f"Crypto-Panda: {total_coins} alerts ({regime})"
    msg['From'] = EMAIL_FROM
    msg['To'] = EMAIL_TO
    msg.attach(MIMEText(html, 'html'))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            recipients = [e.strip() for e in EMAIL_TO.split(",")]
            server.sendmail(EMAIL_FROM, recipients, msg.as_string())
        logger.info(f"Alert email sent: {total_coins} coins")
    except Exception as e:
        logger.error(f"Failed to send alert: {e}")


def scan_universe(universe: str, all_coins: list, all_tickers: dict, end_date: str,
                   top_n: int, min_weighted_score: float) -> list:
    """Scan a single universe and return buy-worthy coins."""
    config = get_universe_config(universe)
    rank_min, rank_max = config["rank_range"]

    coins = [
        c for c in all_coins
        if c.get("is_active") and not c.get("is_new")
        and c.get("rank") is not None
        and rank_min <= c.get("rank", 0) <= rank_max
        and c['id'] not in EXCLUDED_COINS
    ][:top_n]

    logger.info(f"Scanning {len(coins)} {universe}-cap coins (rank {rank_min}-{rank_max})...")

    alerts = []
    for i, coin in enumerate(coins):
        coin_id = coin['id']
        if (i + 1) % 50 == 0:
            logger.info(f"  {universe}: {i+1}/{len(coins)}")

        ticker_data = all_tickers.get(coin_id, {})
        result = scan_coin(coin_id, end_date, ticker_data, config)
        if result is None:
            continue

        result['universe'] = universe

        triggers = []
        if result['rsi'] < 30:
            triggers.append("RSI_OVERSOLD")
        if result.get('consistent_growth'):
            triggers.append("WEEKLY_GROWTH")
        if result.get('monthly_growth'):
            triggers.append("MONTHLY_GROWTH")
        if result.get('volume_spike', 0) >= 0.7:
            triggers.append("VOLUME_SPIKE")
        if result.get('distance_ath_score', 0) >= 0.6:
            triggers.append("ATH_DISCOUNT")
        if result['weighted_pct'] >= min_weighted_score:
            triggers.append("HIGH_SCORE")

        if triggers:
            result['triggers'] = triggers
            alerts.append(result)

        time.sleep(0.15)

    alerts.sort(key=lambda x: x['weighted_pct'], reverse=True)

    # Filter to buy-worthy
    buy_worthy = [
        a for a in alerts
        if a['rsi'] < 70
        and a['change_7d'] < 50
        and a['weighted_pct'] >= min_weighted_score
        and any(t in a.get('triggers', []) for t in ['WEEKLY_GROWTH', 'VOLUME_SPIKE', 'RSI_OVERSOLD'])
    ][:10]  # Top 10 per universe

    logger.info(f"  {universe}: {len(buy_worthy)} buy-worthy from {len(alerts)} triggers")
    return buy_worthy


def run_daily_scan(universe: str = "small", top_n: int = 200, min_weighted_score: float = 20.0):
    """Run the daily scan. If universe='all', scans small/mid/large with separate tables."""
    end_date = datetime.now(timezone.utc).date().isoformat()

    # Market regime
    regime = detect_market_regime_from_btc(end_date)
    logger.info(f"Market regime: {regime}")

    # Fear & Greed
    fng = fetch_fear_and_greed_index()
    logger.info(f"Fear & Greed: {fng}")

    # Fetch coins and tickers once (shared across universes)
    client = Coinpaprika.Client(api_key=COIN_PAPRIKA_API_KEY) if COIN_PAPRIKA_API_KEY else Coinpaprika.Client()
    try:
        all_coins = call_with_retries(client.coins)
    except Exception as e:
        logger.error(f"Failed to fetch coins: {e}")
        return

    try:
        all_tickers = {t['id']: t for t in call_with_retries(client.tickers)}
    except Exception:
        logger.warning("Could not fetch bulk tickers")
        all_tickers = {}

    # Determine which universes to scan
    universes = ["large", "mid", "small"] if universe == "all" else [universe]

    all_buy_worthy = {}
    for u in universes:
        buy_worthy = scan_universe(u, all_coins, all_tickers, end_date, top_n, min_weighted_score)
        if buy_worthy:
            all_buy_worthy[u] = buy_worthy

    total_coins = sum(len(v) for v in all_buy_worthy.values())
    logger.info(f"Total buy-worthy across all universes: {total_coins}")

    if not all_buy_worthy:
        logger.info("No buy-worthy coins found in any universe. No email sent.")
        return

    # Stage 2: Fetch news via Google News RSS (free) for shortlisted coins only
    from coin_analysis import apply_news_confirmation

    total_shortlisted = sum(len(v) for v in all_buy_worthy.values())
    logger.info(f"Stage 2: Fetching news for {total_shortlisted} shortlisted coins via Google News RSS...")

    for u, coins_list in all_buy_worthy.items():
        for coin in coins_list:
            # Use readable coin name for Google News search
            name = coin.get("coin_id", "").split("-", 1)[-1].replace("-", " ") if "-" in coin.get("coin_id", "") else coin.get("coin_id", "")
            apply_news_confirmation(coin, name)

    all_shortlisted = []
    for coins_list in all_buy_worthy.values():
        all_shortlisted.extend(coins_list)
    news_flags = [c.get("news_flag", "N/A") for c in all_shortlisted[:10]]
    logger.info(f"News sentiment applied. Flags: {news_flags}")
    catalysts_found = [c for c in all_shortlisted if c.get("news_catalysts")]
    if catalysts_found:
        logger.info(f"Catalysts detected: {[(c['coin_id'], c['news_catalysts']) for c in catalysts_found[:5]]}")

    # Persist news sentiment to Aurora for future backtesting
    try:
        from data_management import save_news_sentiment_history
        save_news_sentiment_history(all_shortlisted)
    except Exception as e:
        logger.debug(f"Could not persist news sentiment: {e}")

    # Generate LLM commentary for all top coins combined
    all_top = []
    for u, coins_list in all_buy_worthy.items():
        all_top.extend(coins_list[:5])  # Top 5 per universe for commentary
    commentary = generate_llm_commentary(all_top[:15], regime, fng)

    # Log top picks
    for u, coins_list in all_buy_worthy.items():
        for a in coins_list[:5]:
            logger.info(
                f"  [{u:>5s}] {a['coin_id']:30s} RSI={a['rsi']:5.1f} "
                f"7d={a['change_7d']:+7.1f}% W={a['weighted_pct']:5.1f}%"
            )

    send_alert_email(all_buy_worthy, regime, fng, universe, llm_commentary=commentary)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Crypto-Panda Daily Scanner")
    parser.add_argument("--universe", type=str, default="small",
                        choices=["large", "mid", "small", "all"],
                        help="Coin universe (default: small)")
    parser.add_argument("--top-coins", type=int, default=200,
                        help="Max coins to scan (default: 200)")
    parser.add_argument("--min-weighted-score", type=float, default=20.0,
                        help="Min weighted score %% to trigger (default: 20)")
    args = parser.parse_args()

    run_daily_scan(universe=args.universe, top_n=args.top_coins, min_weighted_score=args.min_weighted_score)
