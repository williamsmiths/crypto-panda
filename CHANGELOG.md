# Changelog

All notable changes to this project will be documented in this file.

## [v2.1.0] - 2026-04-11

### Fixed
- Hardcoded `.env` path (`/home/ec2-user/...`) replaced with dynamic path from `__file__` — now runs on any machine
- Relative `LOG_DIR`/`DATA_DIR` paths replaced with absolute paths — no more CWD dependency
- Unsafe `iloc[0]`/`iloc[-1]` on empty DataFrames guarded in `calculate_price_change` and `calculate_volume_change`
- Incomplete return dict from `analyze_coin` on missing price data — now returns all expected keys with zero defaults
- Fear & Greed API unsafe `int(data[0].get("value"))` — now guards against empty list and None
- `AURORA_PORT` type mismatch (`os.getenv` returns string, psycopg2 expects int) — now cast to `int`
- Silent error logging in `process_single_coin` upgraded from `debug` to `error` level
- Results CSV deleted after report — now archived to `processed/` subdirectory
- Inconsistent GPT response access pattern normalized to dict-style across all calls

### Added
- **RSI indicator** — 14-day Relative Strength Index scoring oversold bounces and momentum with volume confirmation (0-1 points)
- **Shared logging module** (`logging_config.py`) — replaces 6 identical `setup_logging()` copies across all modules
- **Startup env var validation** — warns at import time about missing required environment variables
- **`.env.example`** — documents all required and optional environment variables for easy onboarding
- **Batch DB writes** (`save_cumulative_scores_batch`) — single `executemany()` call replaces 1000+ individual connections per run
- **Per-task timeout** — ThreadPoolExecutor uses `submit()` + `as_completed()` with 120s timeout per coin

### Changed
- **Scoring rebalanced** (max score: 22 -> 21):
  - Santiment surge score capped at 3 (was 6), reducing Santiment weight from 36% to 26%
  - `tweet_score` now continuous 0-1 (scales by tweet count, not binary)
  - `fear_and_greed_score` now continuous 0-1 (captures oversold *and* overbought, not just >60)
  - `sentiment_score` now continuous 0-1 (raw VADER compound, not binary >0.5 threshold)
  - `trend_conflict_score` increased to 2 points (was 1) — better weights this early breakout signal
- Surge word fuzzy matching threshold raised from 75% to 85%; short words (<=4 chars) use exact word boundary matching to reduce false positives
- DB schema uses `TIMESTAMP` instead of `DATE` for `coin_data.timestamp` column
- README metric reference table updated to reflect all scoring changes

## [v2.0.0] - 2025-04-11

- Initial public release
