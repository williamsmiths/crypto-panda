
# Crypto-Panda: Automated Crypto Market Scanner & Alert System

[![GitHub Repo](https://img.shields.io/badge/GitHub-sjmoran%2Fcrypto--panda-blue?logo=github)](https://github.com/sjmoran/crypto-panda)
[![License: CC BY-NC 4.0](https://img.shields.io/badge/License-CC--BY--NC%204.0-orange)](https://creativecommons.org/licenses/by-nc/4.0/)
[![Python Version](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/Tests-22%20passing-brightgreen)]()

<img src="./images/crypto_panda_trading.png" alt="Crypto Panda Trading" width="50%"/>

---

## What is Crypto-Panda?

An open-source crypto market scanner that scores coins using backtested quantitative signals, applies LLM-powered news analysis on shortlisted coins, and emails you a daily report with AI commentary, exit targets, and catalyst alerts.

Built with a two-stage architecture that keeps costs low (~$100/mo) by running expensive operations only on pre-qualified coins.

---

## Features

| Feature | Description |
|---|---|
| **Two-Stage Scoring** | Stage 1: quantitative signals on all coins (free). Stage 2: LLM news analysis on shortlist only (~$0.20/run) |
| **Multi-Universe** | Separate analysis and weights for large-cap (1-50), mid-cap (51-200), and small-cap (201-1000) |
| **Evidence-Weighted** | Signal weights derived from 5,600+ backtesting observations, not guesswork |
| **LLM News Analytics** | Crypto-aware sentiment, catalyst detection (exchange listings, hacks, lawsuits), risk identification |
| **News Velocity** | Detects when a coin is getting unusual attention (article count as proxy) |
| **Exit Targets** | Per-coin take-profit and trailing stop-loss, volatility-scaled |
| **Market Regime** | Bull/bear/sideways detection via BTC 50/200 MA crossover |
| **AI Commentary** | LLM generates per-coin analysis (OpenAI, Anthropic, Ollama, or any compatible endpoint) |
| **Backtester** | 4+ years of validation data with volatility-adjusted surge detection and exit strategy simulation |
| **News Persistence** | Daily news sentiment saved to Aurora PostgreSQL for future backtesting |

---

## Quickstart

```bash
git clone https://github.com/sjmoran/crypto-panda.git
cd crypto-panda
pip install -r requirements.txt
cp .env.example .env   # Fill in API keys

# Daily scan — all cap sizes
python daily_scanner.py --universe all --top-coins 200 --min-weighted-score 35

# Weekly full report
python monitor.py

# Backtest
python backtester.py --universe small --weeks 100 --top-coins 50
```

---

## Running Modes

| Mode | Command | What it does | Frequency |
|---|---|---|---|
| **Daily scanner** | `python daily_scanner.py --universe all` | Multi-universe scan with LLM news analysis | Daily via cron |
| **Small-cap focus** | `python daily_scanner.py --universe small` | Rank 201-1000 only | Daily |
| **Weekly report** | `python monitor.py` | Full analysis + LLM report + Excel | Weekly |
| **Backtester** | `python backtester.py --universe small --weeks 100` | Validate signals against history | Ad-hoc |
| **Test email** | `python send_test_email.py` | Sample report with mock data | Ad-hoc |

---

## Two-Stage Architecture

```
Stage 1: Score ALL 200+ coins (free quantitative signals)
  ├── CoinPaprika bulk ticker (1 API call for all coins)
  ├── CoinPaprika historical per coin (~200 calls)
  ├── Fear & Greed Index (1 call)
  ├── 11 signals: price, volume, RSI, growth, FNG, ticker features
  ├── 0 news calls, 0 LLM calls
  └── Output: ranked list → filter to top ~20

Stage 2: LLM News Analysis for TOP ~20 only
  ├── Google News RSS per coin (~20 fetches, free)
  ├── LLM analysis (~$0.01/coin):
  │   ├── Crypto-aware sentiment (-1.0 to +1.0)
  │   ├── Catalyst detection (exchange_listing, hack, lawsuit, etc.)
  │   ├── 1-sentence summary + key risk
  │   └── Confidence score
  ├── News velocity (article count as attention signal)
  ├── Score adjustment: (sentiment × 2 × confidence) + catalyst_bonus + velocity_bonus
  └── Fallback: VADER if LLM unavailable

Stage 3: AI Commentary + Email (~1 LLM call)
```

**Principle:** Expensive operations only run on pre-qualified coins.

---

## Scoring System

### Stage 1: Quantitative Signals (16-point scale)

11 signals scored from price/volume/ticker data. Weights differ per universe based on backtesting.

| Category | Signal | Range | Large-Cap Weight | Small-Cap Weight | Backtested? |
|---|---|---|---|---|---|
| Price | Price Change Score | 0-3 | -1.0 (contrarian) | +1.5 (momentum) | Yes |
| Price | Consistent Weekly Growth | 0-1 | +1.0 | **+3.0** (best signal) | Yes |
| Price | Consistent Monthly Growth | 0-1 | **+3.0** (best signal) | +0.5 | Yes |
| Price | Trend Conflict | 0-2 | +1.5 | -1.0 (harmful) | Yes |
| Volume | Volume Change Score | 0-3 | +1.5 | +1.5 | Yes |
| Volume | Sustained Volume Growth | 0-1 | +0.5 | +1.0 | Yes |
| Technical | RSI Score | 0-1 | **+3.0** | +0.5 | Yes |
| Market | Fear & Greed | 0-1 | +1.0 | +0.5 | No |
| Ticker | Volume Spike 24h | 0-1 | +1.0 | +3.0 | No (live only) |
| Ticker | Distance from ATH | 0-1 | +0.5 | +2.0 | No (live only) |
| Ticker | Multi-TF Momentum | 0-1 | -0.5 (contrarian) | +1.5 | No (live only) |

**Key finding:** Signals behave OPPOSITE between large and small caps. Momentum chasing hurts large caps but helps small caps. RSI oversold bounces are strong for large caps but weak for small caps.

### Stage 2: News Confirmation (LLM-powered)

Applied only to shortlisted coins. Adjusts weighted score by up to ±4.0.

| Component | What it does | Adjustment |
|---|---|---|
| **LLM Sentiment** | Crypto-aware analysis of 20 Google News headlines | sentiment × 2.0 × confidence |
| **Catalyst Detection** | Exchange listing (+1.5), partnership (+0.5), hack (-2.0), lawsuit (-1.5), regulatory (-1.0) | Per catalyst |
| **News Velocity** | 15+ articles = high attention (+0.5), 8+ = medium (+0.2) | Bonus |
| **Fallback** | VADER sentiment if LLM unavailable | sentiment × 2.0 |

---

## Backtesting Results

### Large-Cap (4-Year: May 2022 - Sep 2024, 22 coins, 2,518 observations)

| Metric | Equal-Weighted | Evidence-Weighted |
|---|---|---|
| 7d correlation | 0.021 | **0.054** (2.6x better) |
| 7d top 20% return | +1.15%/week | **+1.99%/week** |
| 30d top 20% return | +3.25%/month | **+4.29%/month** |

**Best signals:** Monthly growth (+1.20%), Trend conflict (+1.52%), RSI (+0.89%).

### Small-Cap (2-Year: Apr 2024 - Mar 2026, 50 coins, 3,140 observations)

| Metric | Result |
|---|---|
| 7d score correlation | **0.068** (strongest of any universe) |
| Top 20% vs bottom 20% spread | **+2.77%/week** |
| 30d avg peak return | **+18.40%** (but endpoint only -0.21%) |
| Best exit strategy | **Trailing stop (+1.11%)** — only profitable strategy |

**Best signals:** Weekly growth (+2.31%), Volume (+0.81%), Price momentum (+0.68%).

### Bear Market (Oct 2025 - Mar 2026, 584 observations)

| Metric | Result |
|---|---|
| Weighted top 20% + combined exit | **+3.48%** |
| Weighted bottom 20% | **-6.02%** |
| Spread | **+9.50%** |

### Key Takeaways

1. **Evidence-weighted scoring works** — beats equal-weighted across 4 years
2. **Signals behave opposite between cap sizes** — one set of weights does NOT fit all
3. **Exit timing matters more than entry** — 10-18% of returns left on table without stops
4. **Most signals are noise** — only 3-4 of 11 consistently correlate with returns
5. **Simplicity wins** — removing Santiment, keywords, tweets improved performance

---

## Cost Philosophy

Started at $170/mo in v1. Now $100/mo with better results. Every dependency was earned or removed.

**Removed (no measurable value in backtesting):**
- Santiment API ($100/mo) — on-chain metrics showed zero correlation
- CryptoNews API ($0-30/mo) — replaced with free Google News RSS
- Tweet score — just counted tweets, no quality signal
- Surge keyword matching — fuzzy matching, high false positives
- Digest score — binary presence detection
- Event score — just "event exists"

**What remains:**

| Source | Cost | Why it earned its place |
|---|---|---|
| CoinPaprika Starter | $99/mo | 5yr history, real-time tickers. Powers all backtestable signals. |
| Google News RSS | Free | 20 headlines/coin. Stage 2 only (~20 queries/run). |
| Alternative.me | Free | Fear & Greed Index (1 call/run). |
| CoinGecko | Free | Fallback if no CoinPaprika key. |
| VADER | Free (local) | Fallback if LLM unavailable. |
| LLM | ~$1-3/run | News analysis + commentary. Or $0 with local Ollama. |
| Brevo SMTP | Free | 300 emails/day. |
| **Total** | **~$100/mo** | |

---

## Architecture

```
daily_scanner.py          # Daily: two-stage scan, LLM news, email
monitor.py                # Weekly: full analysis, LLM report, Excel
backtester.py             # Validate signals against 4+ years of data

coin_analysis.py          # Scoring engine + LLM news analysis + Google News
coin_universe.py          # Per-universe weights, exit targets, rank ranges
features.py               # Volume spike, ATH distance, MTF momentum
api_clients.py            # CoinPaprika, Fear & Greed
report_generation.py      # LLM abstraction, HTML email, Excel
data_management.py        # Aurora PostgreSQL + news sentiment persistence
config.py                 # Configuration
logging_config.py         # Shared logging
plotting.py               # Charts
send_test_email.py        # Test with mock data
```

**14 modules, ~5,200 lines, 22 unit tests.**

---

## Environment Variables

See [`.env.example`](.env.example). Key ones:

| Variable | Required | Description |
|---|---|---|
| `COIN_PAPRIKA_API_KEY` | Yes | CoinPaprika Pro ($99/mo) |
| `OPENAI_API_KEY` | For LLM features | Or set `LLM_PROVIDER` for alternatives |
| `LLM_PROVIDER` | No | `openai` (default), `anthropic`, `ollama` |
| `LLM_MODEL` | No | Default: `gpt-4.1` |
| `LLM_BASE_URL` | No | Custom endpoint for Ollama, vLLM |
| `EMAIL_FROM` | Yes | Verified sender address |
| `EMAIL_TO` | Yes | Recipient(s) |
| `SMTP_SERVER` | Yes | e.g. `smtp-relay.brevo.com` |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | Yes | SMTP credentials |

---

## Disclaimer

> **THIS SOFTWARE IS NOT FINANCIAL ADVICE AND SHOULD NOT BE RELIED UPON FOR INVESTMENT DECISIONS.**
>
> Crypto-Panda is an **educational and research tool only**. The scoring system, backtesting results, and AI-generated outputs are provided for informational purposes only. The author is not a licensed financial adviser.
>
> **Key risks:**
> - Backtesting does not guarantee future results. Correlations are weak (0.02-0.07) and may not persist.
> - Cryptocurrency markets are extremely volatile. You can lose all of your investment.
> - Small-cap coins carry additional risks: low liquidity, manipulation, rug pulls, total loss.
> - LLM-generated analysis may contain errors or hallucinations.
> - No warranty is provided. Software is "as is."
>
> You are solely responsible for your own decisions. Always DYOR and consult a qualified financial adviser. Never invest money you cannot afford to lose.

---

## License

Licensed under [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/). See [LICENSE](LICENSE).

---

## Acknowledgments

- [CoinPaprika API](https://api.coinpaprika.com/)
- [CoinGecko API](https://www.coingecko.com/en/api)
- [Google News RSS](https://news.google.com/)
- [Fear and Greed Index](https://alternative.me/crypto/fear-and-greed-index/)
- [OpenAI](https://openai.com/) / [Anthropic](https://anthropic.com/)
