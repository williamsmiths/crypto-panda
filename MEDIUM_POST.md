# I Backtested an AI Crypto Scanner Over 4 Years — Here's What the Data Showed

## An experiment in signal analysis, evidence weighting, and the limits of prediction in cryptocurrency markets.

The Cryptocurrency market generates an extraordinary volume of data every second — price movements, trading volumes, social sentiment, news events. The sheer scale of this information creates both an opportunity and a challenge: somewhere in this noise may be patterns that correlate with subsequent price movements. Whether those patterns can be identified systematically, and whether any observed correlations persist out of sample, are open research questions.

I set out to explore these questions by building [CryptoPanda](https://github.com/sjmoran/crypto-panda) 🐼, an open-source experimental tool that scans the crypto market daily, scores coins using quantitative signals, and delivers analytical summaries through an automated email report. The signal weights are not based on intuition or conventional wisdom — they are derived from backtesting across 4 years and 5,600+ observations.

**A note on scope:** CryptoPanda is a research and methodology exercise, not a recommendation engine. The backtesting results documented in this article are historical, the correlations are weak, and the tool does not reliably predict cryptocurrency prices. This article describes the analytical approach and what the data revealed — it is not an invitation to trade.

What I discovered along the way challenged several of my assumptions about how crypto markets behave, and revealed that the relationships between signals and outcomes are more nuanced — and more fragile — than I initially expected.

---

## The Research Question

The Cryptocurrency market is volatile in a way that defies most conventional financial models. Individual coins can move 20% in a single day. Market sentiment shifts rapidly, driven by regulatory announcements, whale movements, social media trends, and macroeconomic events. The pace of change is breathtaking.

Within this environment, a compelling research question emerges: **given the wealth of available data, to what extent do quantitative signals correlate with near-term cryptocurrency price movements?** And can we build a systematic framework to measure those correlations rigorously?

Surprisingly, I found very little prior open-source work addressing this question with transparent methodology. There are many crypto analysis tools that claim predictive power, but very few that publish their backtesting approach alongside their claims. I wanted to build something that was both analytically useful and honest about its limitations.

The result was CryptoPanda — named for its reliance on the Pandas library for data analysis, and its focus on cryptocurrency trend detection. The tool is fully [open source on GitHub](https://github.com/sjmoran/crypto-panda), comprising 14 Python modules (~5,200 lines of code) with 22 unit tests.

---

## What CryptoPanda Produces

The primary output is a daily HTML email report designed for rapid analytical review:

Example report
*Figure 1: A CryptoPanda daily report showing model-generated signal classifications, exit scenarios, and market regime context. Source: Image by author.*

Each coin in the report is accompanied by an LLM-generated commentary — classifying the coin as higher-conviction, neutral, or lower-conviction — along with a natural language summary of the underlying signals. The LLM considers the coin's RSI, growth consistency, volume dynamics, distance from all-time high, and composite score to produce its assessment. The LLM layer is provider-agnostic, supporting OpenAI, Anthropic Claude, Ollama (for fully local inference), or any OpenAI-compatible endpoint.

The email is structured with separate colour-coded tables for each coin universe: large-cap (rank 1–50), mid-cap (51–200), and small-cap (201–1000). This segmentation is not cosmetic — as the backtesting revealed, **signals exhibit fundamentally different correlation patterns across market cap ranges**, making a single unified scoring system analytically inadequate.

Each coin includes model-generated exit scenarios — take-profit and stop-loss levels scaled to that coin's historical volatility. These are analytical reference points for research purposes, not trading instructions. A market conditions header provides context on the current regime (bull, bear, or sideways — inferred from Bitcoin's 50/200-day moving average crossover) and the Fear & Greed Index, both explained in plain English. A comprehensive glossary at the top of the email defines every column and flag for readers who may be unfamiliar with the terminology.

The tool generates analytical outputs. Any decision to act on those outputs — including any decision to buy, sell, or hold any cryptoasset — remains entirely the reader's responsibility.

---

## System Architecture

The two-stage design is central to how CryptoPanda manages cost and analytical quality:

CryptoPanda Architecture
*Figure 2: CryptoPanda's two-stage architecture. Stage 1 scores all coins using free quantitative signals. Stage 2 applies LLM-powered news analysis only to the top ~20 shortlisted coins. The backtester validates signal weights against 4+ years of historical data. Source: Image by author.*

The pipeline is organised into the following modules, each with a clear separation of concerns:

- **Configuration** (`config.py`): Environment variables, thresholds, and settings.
- **Coin Universe** (`coin_universe.py`): Three distinct profiles — large-cap, mid-cap, and small-cap — each with their own signal weights, exit scenarios, and rank ranges. All derived from backtesting.
- **API Clients** (`api_clients.py`): Data ingestion from CoinPaprika (price, volume, historical OHLCV, real-time tickers) and Alternative.me (Fear & Greed Index).
- **Feature Engineering** (`features.py`): Extraction of real-time signals from CoinPaprika's ticker endpoint: 24-hour volume spike detection, distance from all-time high, and multi-timeframe momentum alignment.
- **Coin Analysis** (`coin_analysis.py`): The core scoring engine — 11 quantitative signals combined through evidence-weighted scoring, plus a second-stage LLM-powered news analysis function that fetches headlines via Google News RSS (free, no API key) and analyses them for crypto-aware sentiment, catalyst detection, and risk identification.
- **Report Generation** (`report_generation.py`): LLM abstraction layer (supporting OpenAI, Anthropic, Ollama, and any compatible endpoint), HTML email composition, and Excel export.
- **Daily Scanner** (`daily_scanner.py`): The two-stage daily pipeline — quantitative scoring of all coins (stage 1), LLM news analysis of shortlisted coins only (stage 2), commentary generation, and email delivery.
- **Weekly Monitor** (`monitor.py`): The comprehensive weekly analysis with full LLM-driven report and Excel attachment.
- **Backtester** (`backtester.py`): Signal validation against 4+ years of historical price data, with volatility-adjusted surge detection, exit strategy simulation, and market regime overlay.
- **Data Management** (`data_management.py`): Aurora PostgreSQL persistence for historical scores, detailed sub-scores, and daily news sentiment records for future backtesting.

---

## The AI Design Decision: Supervised vs. Unsupervised

A foundational design question in any analytical system is whether to adopt a supervised or unsupervised approach. For CryptoPanda, I chose an unsupervised methodology, and the reasoning is worth examining.

A supervised approach to crypto price movement analysis would frame the problem as computing the probability of a price increase at a given time, conditioned on historical features such as news sentiment, price trajectories, and volume patterns. This formulation requires labelled training data — annotated examples of significant price events across many coins and time periods. The collection of such labels would be a substantial manual effort, and the labels themselves are inherently ambiguous (what constitutes a "significant move" for a $50 billion asset versus a $50 million one?).

Beyond the labelling challenge, supervised models in financial time series face persistent issues with data drift. Covariate shift is a particular concern: the features that correlate with price movements evolve over time. Terms like "NFT" may have been strongly associated with upward moves in 2021 but carry little signal in 2025, while "layer 2 scaling" may have gained relevance. Concept drift, label distribution shift, and data quality drift compound these issues, requiring continuous model retraining with fresh annotations.

For a side project where simplicity and maintainability were paramount, this ongoing annotation burden was prohibitive. I chose instead to build a weighted ensemble of threshold-based and continuous classifiers — each evaluating a single market signal and contributing a score proportional to its strength. This approach requires no labels, is trivially interpretable, and permits rapid adjustment of individual thresholds.

The critical evolution came in version 3: I took these "sensibly set" thresholds and **validated them against 4 years of historical price data.** Several thresholds that seemed reasonable from first principles turned out to be negatively correlated with future returns — a finding that would have been invisible without systematic backtesting.

---

## Threshold-Based Classifiers and Large Language Models: An Unusual Pairing

CryptoPanda's scoring engine sits at the opposite end of the model complexity spectrum from large language models. Each signal in the system evaluates a single market feature against one or more thresholds and produces a score. The signals vary in their output characteristics:

- **Binary classifiers** produce a simple 0 or 1 output — for example, "did the price close higher on 4+ of the last 7 days?" These are the simplest components, directly analogous to classical decision stumps.
- **Multi-threshold classifiers** evaluate a feature at several levels, producing a graduated score. The volume spike signal, for instance, scores 0.4 for a 20% 24-hour volume increase, 0.7 for 50%, and 1.0 for 100%+. The price change and volume change signals evaluate three timeframes independently, each contributing 0 or 1, for a maximum of 3.
- **Continuous classifiers** map a raw input onto a 0–1 scale. The Fear & Greed Index is rescaled from its 0–100 range onto a continuous 0–1 score. The volume spike signal scores 0.4 at 20%, 0.7 at 50%, and 1.0 at 100%+.

These 11 stage-1 signals are aggregated through a **weighted voting scheme**, where each signal's weight reflects its empirically measured correlation with subsequent returns in backtesting. The composite score represents the degree to which multiple independent market signals align for a given coin at a given time. A second stage then applies LLM-powered news analysis — but only on the shortlisted coins that scored well in stage 1, keeping costs low.

The LLM serves a complementary function. It does not participate in scoring — its role is to **summarise** the quantitative outputs in natural language. Given a coin's RSI, growth consistency, volume dynamics, and composite score, the LLM produces a concise classification with an accompanying explanation. This division of labour exploits the strengths of each approach: transparent, reproducible quantitative scoring on one side; nuanced, human-readable synthesis on the other.

The LLM layer supports multiple providers. Setting `LLM_PROVIDER=ollama` and pointing to a local endpoint enables fully offline operation at zero API cost — a meaningful consideration for a tool designed to run daily.

---

## Worked Example: The Volume Change Signal

To illustrate the threshold-based scoring methodology concretely, consider the volume change signal. The objective is to assess whether a cryptocurrency is experiencing unusual trading volume, which has historically been associated with subsequent price movements in some contexts.

The signal evaluates percentage change in trading volume across three time windows — short-term (7 days), medium-term (30 days), and long-term (90 days). Example thresholds for a mid-cap coin with medium volatility:

- Short-term: 20% increase
- Medium-term: 15% increase
- Long-term: 10% increase

Exceeding any threshold contributes +1 to the cumulative score (maximum of 3 for this signal).

The threshold calibration is where the nuance lies. Volatility determines what constitutes a "significant" volume change: a 20% spike is unremarkable for a highly volatile micro-cap but noteworthy for a stable large-cap. Market cap determines the baseline expectation for volume activity. CryptoPanda classifies each coin by both dimensions and applies differentiated thresholds accordingly.

The backtesting results for this signal were instructive. On large-cap coins, volume surges exhibited a **negative** correlation with subsequent 7-day returns (-0.52% average lift) — coins experiencing unusual volume tended to mean-revert. On small-cap coins, the same signal showed a modest positive correlation (+0.81%). This divergence — where an identical signal correlates positively in one context and negatively in another — motivated the development of the per-universe weighting system.

---

## The Evidence-Weighted Scoring System

CryptoPanda began with five threshold-based classifiers, each weighted equally. Through iterative development and rigorous pruning — removing signals that backtesting showed were noise — the system arrived at an 11-signal first stage with a separate LLM-powered news stage. The most significant architectural change was the transition from equal weighting to **evidence weighting**, where each signal's contribution is proportional to its empirically measured correlation with subsequent returns.

### Stage 1: The 11 Quantitative Signals

1. **Price Change Score (0–3):** EMA-smoothed price momentum across short, medium, and long-term windows. Market-cap and volatility-adjusted thresholds.
2. **Volume Change Score (0–3):** Volume dynamics across the same three windows with analogous threshold adjustment.
3. **Consistent Weekly Growth (0–1):** Binary indicator: positive price movement on 4+ of the last 7 days. Backtesting identified this as **the signal most strongly correlated with subsequent small-cap returns** (+2.31% average weekly lift in the sample period).
4. **Consistent Monthly Growth (0–1):** 18+ up-days in a 30-day window. **The strongest signal for large-cap returns in backtesting** (+1.20% average weekly lift).
5. **Sustained Volume Growth (0–1):** Volume increased on 4+ of the last 7 days.
6. **Trend Conflict (0–2):** Fires when a monthly uptrend exists without weekly confirmation. This pattern may signal accumulation. It exhibited the most dramatic universe divergence in backtesting: +1.52% lift on large caps, -1.31% on small caps.
7. **RSI Score (0–1):** 14-day Relative Strength Index. Scores when RSI < 30 (oversold) or RSI > 70 with volume confirmation. Showed consistent correlation over 4 years on large caps (+0.89% lift).
8. **Fear & Greed (0–1):** Continuous scale from the Alternative.me index, capturing market-wide sentiment from extreme fear (0) to extreme greed (100).
9. **Volume Spike 24h (0–1):** Real-time 24-hour volume change from the CoinPaprika ticker. A +100% spike scores 1.0, +50% scores 0.7, +20% scores 0.4.
10. **Distance from ATH (0–1):** How far the current price sits below the coin's all-time high. The scoring assigns highest weight to the -50% to -85% range: deep enough to represent a genuine discount, not so deep as to suggest an abandoned project.
11. **Multi-Timeframe Momentum (0–1):** Alignment of price changes across 1-hour, 6-hour, 24-hour, and 7-day windows. All four positive = 1.0 (strong aligned momentum).

### Stage 2: LLM-Powered News Analysis (shortlisted coins only)

An earlier version of CryptoPanda included news sentiment and trending scores as first-stage signals, weighted equally with price and volume data. Backtesting could not validate these signals, and the news API (CryptoNews) was a paid dependency whose free tier frequently expired.

The current design takes a different approach. News analysis is deferred to a second stage that runs **only on the ~20 coins that scored highest in stage 1.** This has two advantages: it reduces API usage from 200+ calls to ~20, and it ensures that news sentiment is evaluated in context — knowing that a random low-scoring coin has positive headlines is uninformative, but knowing that a high-scoring coin also has confirming (or contradicting) news is genuinely useful.

Stage 2 fetches 20 recent headlines per coin via **Google News RSS** (free, no API key, no rate limits) and sends them to the LLM with a crypto-specific prompt. The LLM returns:

- **Sentiment** (-1.0 to +1.0) with crypto-aware understanding ("moon" is bullish, "rug pull" is bearish — nuances that the VADER lexicon, which was trained on general social media text, misses entirely)
- **Catalyst detection**: classification of news into categories such as exchange listing (+1.5 score adjustment), partnership (+0.5), hack or exploit (-2.0), regulatory action (-1.0), or lawsuit (-1.5)
- **A one-sentence summary** and **key risk identification**
- A **confidence score** that scales the adjustment (uncertain reads contribute less)

The system also tracks **news velocity** — how many articles a coin is generating. A coin receiving 15+ articles in a day is getting unusual attention, regardless of sentiment, and receives a small velocity bonus (+0.5).

The total news adjustment can range from approximately -4.0 to +4.0, applied on top of the stage-1 weighted score. If the LLM is unavailable, the system falls back to VADER sentiment analysis (free, local, no API dependency).

All news data — sentiment, catalysts, velocity, summaries — is persisted daily to Aurora PostgreSQL. Over time, this builds a historical news dataset that will enable backtesting of news signals, closing the validation gap that currently exists for this stage of the pipeline.

### Evidence Weighting

The original system summed all signals equally. After backtesting across 2,518 large-cap and 3,140 small-cap observations, adjusted weights were derived for each universe:

**Large-Cap Weights (backtesting suggested a contrarian tilt):**


| Signal         | Backtested Lift | Assigned Weight     |
| -------------- | --------------- | ------------------- |
| RSI (oversold) | +0.89%          | **3.0**             |
| Monthly Growth | +1.20%          | **3.0**             |
| Volume Change  | -0.52%          | +1.5 (reduced)      |
| Trend Conflict | +1.52%          | +1.5                |
| Price Change   | -0.34%          | **-1.0** (inverted) |


**Small-Cap Weights (backtesting suggested a momentum tilt):**


| Signal         | Backtested Lift | Assigned Weight     |
| -------------- | --------------- | ------------------- |
| Weekly Growth  | +2.31%          | **3.0**             |
| Volume Change  | +0.81%          | +1.5                |
| Price Change   | +0.68%          | **+1.5** (positive) |
| Trend Conflict | -1.31%          | **-1.0** (inverted) |
| RSI            | +0.22%          | +0.5 (reduced)      |


The negative weight on Price Change for large caps reflects a mean-reversion pattern observed in the data: coins that had already appreciated significantly tended to revert in the subsequent period. On small caps, recent appreciation was positively correlated with further appreciation — a momentum pattern. Whether these patterns persist out of sample remains an open question.

---

## Backtesting Methodology and Results

The backtester validates the scoring system against historical data using a walk-forward approach. At each weekly checkpoint, coins are scored using only data available at that point in time, and the actual price trajectory over the subsequent 7 and 30 days is recorded.

Several design choices distinguish this backtester from naive approaches:

- **Volatility-adjusted classification:** A "significant move" is defined relative to each coin's expected volatility (2x the coin's historical daily standard deviation scaled to the time window), not a fixed percentage threshold.
- **Peak return tracking:** The highest price within each window is recorded alongside the endpoint price, revealing how much of the observed price movement was captured at the endpoint versus the intra-window peak.
- **Exit strategy simulation:** Three strategies are evaluated — trailing stop-loss, take-profit, and combined — all with volatility-scaled parameters per coin.
- **Market regime overlay:** Each week is classified as bull, bear, or sideways based on Bitcoin's 50/200-day moving average crossover.

**Important caveat:** These backtesting results are subject to significant limitations including survivorship bias (coins that were delisted or went to zero may be underrepresented), potential look-ahead bias in the weight derivation (weights were informed by the same dataset), and the absence of real-world execution costs (slippage, fees, spread). The correlations are weak and may not persist.

### Large-Cap Results (4 Years: May 2022 – Sep 2024, 22 coins, 2,518 observations)

This test spans a complete market cycle: the 2022 crash, the 2023 recovery, and the 2024 bull run.


| Metric                      | Equal-Weighted | Evidence-Weighted |
| --------------------------- | -------------- | ----------------- |
| 7d correlation with returns | 0.021          | 0.054             |
| Top 20% avg weekly return   | +1.15%         | +1.99%            |
| Top 20% avg monthly return  | +3.25%         | +4.29%            |


The evidence-weighted scoring showed a modestly stronger correlation with subsequent returns compared to equal weighting across the sample period.

### Small-Cap Results (2 Years: Apr 2024 – Mar 2026, 50 coins, 3,140 observations)


| Metric                       | Result          |
| ---------------------------- | --------------- |
| 7d score-return correlation  | 0.068           |
| Top 20% vs bottom 20% spread | +2.77% per week |
| Top 20% avg 30-day return    | +5.63%/month    |


Small caps showed the strongest score-return correlation of any universe in the sample, though the absolute magnitude remains modest and is not a reliable basis for trading decisions.

### The Peak vs. Endpoint Observation

This finding deserves particular attention. Across all backtests:

- **30-day average peak return:** +13.45% (large cap), +18.40% (small cap)
- **30-day average endpoint return:** +3.39% (large cap), -0.21% (small cap)

Coins routinely reached substantially higher prices within a 30-day window before reverting toward their starting price. In the backtesting simulation, a trailing stop-loss — a theoretical sell trigger that follows the price upward but never downward — captured more of the intra-window return than a hold-to-endpoint approach on small caps (+1.11% average simulated return versus -0.14% for hold-to-endpoint).

This observation is historical and simulated. Real-world execution would involve slippage, fees, and timing constraints that are not modelled.

### Bear Market Results (Oct 2025 – Mar 2026, 584 observations)


| Metric              | Result            |
| ------------------- | ----------------- |
| Weighted top 20%    | +3.48% avg return |
| Weighted bottom 20% | -6.02% avg return |
| Spread              | +9.50%            |


The scoring system's correlation with returns appeared most pronounced in the bearish sample period, where the primary observed pattern was avoidance of the lowest-scoring coins.

---

## Correlation Analysis: Signal Relationships

An examination of the inter-signal correlation structure yielded several observations that informed the weighting scheme:

**Price momentum emerged as the strongest individual contributor** to the composite score, but its correlation with subsequent returns was universe-dependent — positive for small caps, negative for large caps in the sample period.

**Weekly growth and monthly growth were moderately correlated** (~0.4), but appeared to serve distinct analytical functions. Weekly growth showed the strongest short-term correlation for small caps; monthly growth for large caps.

**RSI exhibited near-independence** from all other signals (~0.05 correlation), making it a valuable orthogonal input that captures a dimension of market dynamics — overbought and oversold conditions — not represented by trend-following signals.

**Trend conflict was negatively correlated with consistent growth** (-0.3), as expected from its definition (monthly growth without weekly confirmation). In the backtesting sample, this made it a useful contrarian signal on large caps but a negatively correlated signal on small caps.

**The news analysis stage cannot yet be backtested** because it requires live headlines not available in historical archives. This is why news was moved to a separate second stage rather than mixed into the core scoring: it allows the quantitative signals to be validated independently. CryptoPanda now persists daily news sentiment, catalysts, and velocity to Aurora PostgreSQL, building the dataset that will eventually enable backtesting of the news stage as well.

---

## Deployment

CryptoPanda is designed for automated daily operation. Two execution modes are provided:

**Daily Scanner** (`daily_scanner.py`): A lightweight scan of 200+ coins across all cap sizes, generating an email containing higher-scoring coins with LLM-generated commentary. Execution time is approximately one minute. A typical cron configuration:

```bash
0 8 * * * cd /path/to/crypto-panda && python daily_scanner.py --universe all --top-coins 200 --min-weighted-score 35
```

**Weekly Report** (`monitor.py`): A comprehensive analysis of the full coin universe with detailed LLM commentary, Excel attachment, and historical score charts.

Infrastructure costs are modest:


| Component                                                      | Monthly Cost  |
| -------------------------------------------------------------- | ------------- |
| CoinPaprika Starter (5-year historical data, 400K calls/month) | $99           |
| LLM API calls (~$1–3/run, or $0 with local Ollama)             | ~$30–90       |
| SMTP delivery (Brevo free tier, 300 emails/day)                | $0            |
| Compute (EC2 t2.micro or equivalent)                           | $5–20         |
| **Total**                                                      | **~$100–120** |


The cost structure reflects a deliberate philosophy of earning each dependency. Earlier versions of the tool included the Santiment API ($100/month) for on-chain metrics, the CryptoNews API for news articles, tweet counting, event detection, and keyword matching — totalling approximately $170/month. After systematic backtesting revealed that none of these additions measurably improved the scoring system's correlation with returns, they were removed. News analysis was redesigned as a free second stage using Google News RSS and LLM-powered sentiment (replacing VADER, which lacked crypto-specific understanding). The tool's analytical performance improved whilst costs decreased — a useful reminder that more data does not always improve analytical outcomes.

---

## Reflections and Limitations

Building CryptoPanda across three major versions produced several observations that I believe are worth sharing:

**Most signals appear to be noise.** Of 11 stage-1 signals in the current system, only 3–4 exhibited consistent correlations with subsequent returns across backtesting periods. Several signals that seemed intuitively important — tweet counts, event presence, trending mentions, keyword matching — were removed entirely after backtesting showed no measurable value. The stage-2 news analysis, powered by an LLM rather than the original VADER lexicon, is a more promising approach but cannot yet be validated historically.

**Signal-return relationships differed across market cap ranges.** Price momentum correlated positively with subsequent small-cap returns and negatively with large-cap returns in the sample. RSI oversold conditions correlated more strongly with large-cap returns. Trend conflict was positively correlated for large caps and negatively for small caps. These divergences, if they persist, suggest per-universe configurations are analytically necessary.

**Intra-window price dynamics were striking.** Small-cap coins averaged +18.40% peak return within 30 days but only -0.21% at the endpoint in the sample. The gap between peak and endpoint — representing theoretical unrealised gains — substantially exceeded the scoring system's observed correlation with returns. In backtesting simulations, trailing stop-loss rules captured more of the intra-window price movement than hold-to-endpoint approaches.

**Simplicity improved analytical outcomes.** The most analytically effective version of CryptoPanda has fewer signals, fewer data sources, and less complexity than its predecessors. Removing the Santiment integration, fuzzy keyword matching, and event detection improved score-return correlations in the sample. Each of these features appeared to add noise that diluted the signals from the more informative indicators.

**The LLM contributes readability, not analytical power.** The LLM layer generates clear, contextual commentary that makes the tool's outputs accessible. It does not improve the underlying scoring. The analytical value — such as it is — resides in the quantitative signal processing and evidence-weighted scoring.

**All findings are historical and uncertain.** The correlations documented here (0.02–0.07) are weak by statistical standards. They are statistically distinguishable from zero over thousands of observations, but they explain only a small fraction of the variance in cryptocurrency returns. The honest conclusion is that crypto markets appear to be largely unpredictable, and the value of a framework like CryptoPanda — if any — lies in the narrow margin where systematic analysis may modestly improve analytical discipline.

---

## Conclusion

CryptoPanda represents an attempt to bring quantitative rigour to a domain often characterised by unvalidated claims. The two-stage architecture — quantitative scoring first, LLM-powered news analysis second — creates a system that is cost-efficient, analytically transparent, and human-readable.

The backtesting results are consistent in their direction — the evidence-weighted scoring system outperformed equal weighting across all tested universes and market regimes in the historical sample — whilst the absolute magnitude of the observed correlations remains modest. Whether these patterns persist in future market conditions is unknown.

The tool is fully [open source on GitHub](https://github.com/sjmoran/crypto-panda). The backtester, daily scanner, signal weights, and all methodology are transparent and reproducible. I welcome scrutiny, criticism, and contributions from the community.

---

### Disclaimer

This article reflects my personal views only, not those of my employer past or present, or any organisation with which I am or have been affiliated. All content is provided in a personal capacity.

This article and the CryptoPanda software are provided for **informational, educational, and research purposes only**. Nothing in this article constitutes financial advice, investment advice, trading advice, tax advice, legal advice, or any other form of professional advice. The author is not a licensed or regulated financial adviser.

All backtesting results, scoring outputs, signal correlations, and return figures presented in this article are **historical and experimental** in nature. They are derived from past data and are subject to significant limitations including survivorship bias, potential look-ahead bias, and the absence of real-world execution costs. **Past performance is not indicative of future results.** The observed correlations are weak (0.02–0.07) and may not persist.

Cryptoassets are **high-risk and speculative**. Prices can fall rapidly and you may lose some or all of your capital. Small-cap cryptoassets carry additional risks including low liquidity, price manipulation, and complete loss of value. This article does not invite, induce, or encourage any person to buy, sell, or hold any cryptoasset.

Readers are solely responsible for their own decisions. Always conduct your own independent research and, where appropriate, consult a qualified and regulated financial adviser before making any financial decisions. Never commit capital you cannot afford to lose.

---

### 📚 Further Learning

- [CoinPaprika API](https://coinpaprika.com/api/) — Price data, 5-year historical OHLCV, real-time tickers. Primary data source.
- [Google News RSS](https://news.google.com/) — Free news headlines, per-coin searchable. Powers the stage-2 news analysis.
- [Alternative.me Fear & Greed Index](https://alternative.me/crypto/fear-and-greed-index/) — Market-wide sentiment tracking.
- [OpenAI API](https://openai.com/) / [Anthropic API](https://anthropic.com/) — LLM providers for news analysis and commentary.
- [CoinGecko API](https://www.coingecko.com/en/api) — Free alternative for historical price data (365-day limit).
- [VADER Sentiment Analysis](https://github.com/cjhutto/vaderSentiment) — Fallback sentiment scoring when LLM is unavailable.

