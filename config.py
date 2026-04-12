import os
import logging
from dotenv import load_dotenv  # Allows loading environment variables from a .env file
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer  # Sentiment analysis tool

_logger = logging.getLogger(__name__)

# Derive base directory from this file's location
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Path to your .env file where secrets and config are stored
DOT_ENV_PATH = os.path.join(_BASE_DIR, '.env')

# Load environment variables from the specified .env file
load_dotenv(dotenv_path=DOT_ENV_PATH)


# Directory to store logs
LOG_DIR = os.path.join(_BASE_DIR, '..', 'logs')

# Directory to store data files (e.g., price data, tickers)
DATA_DIR = os.path.join(_BASE_DIR, '..', 'data')

# Daily trading volume thresholds to assess liquidity risk by market cap
LOW_VOLUME_THRESHOLD_LARGE = 1_000_000   # Large-cap coins considered illiquid if volume < $1M
LOW_VOLUME_THRESHOLD_MID = 500_000       # Mid-cap coins considered illiquid if volume < $500K
LOW_VOLUME_THRESHOLD_SMALL = 100_000     # Small-cap coins considered illiquid if volume < $100K

# Email configuration variables, pulled from environment
EMAIL_FROM = os.getenv('EMAIL_FROM')           # Sender email address
EMAIL_TO = os.getenv('EMAIL_TO')               # Recipient email address
SMTP_SERVER = os.getenv('SMTP_SERVER')         # SMTP server address (e.g., smtp.gmail.com)
SMTP_USERNAME = os.getenv('SMTP_USERNAME')     # SMTP login username
SMTP_PASSWORD = os.getenv('SMTP_PASSWORD')     # SMTP login password
SMTP_PORT = 587                                # SMTP port (587 is standard for TLS)
MAX_POSSIBLE_SCORE = 16 # Sum: price(3)+volume(3)+growth(1)+vol_growth(1)+fng(1)+monthly(1)+conflict(2)+rsi(1)+vol_spike(1)+ath_dist(1)+mtf(1). News sentiment applied in stage 2 only.

# File paths used in the analysis pipeline
RESULTS_FILE = os.path.join(LOG_DIR, "surging_coins.csv")    # Where analysis results are saved
CRYPTO_NEWS_TICKERS = os.path.join(DATA_DIR, "tickers.csv") # List of tickers for filtering news

# Thresholds used to score coins
FEAR_GREED_THRESHOLD = 60               # Only consider coins if fear/greed index > 60
HIGH_VOLATILITY_THRESHOLD = 0.05        # >5% daily price movement is high volatility
MEDIUM_VOLATILITY_THRESHOLD = 0.02      # 2–5% is medium volatility
NUMBER_OF_TOP_COINS_TO_MONITOR = 3000     # Limit number of top coins considered in reports

# Control flags for running/testing
TEST_ONLY = False                       # Set to True to test without triggering actions
MAX_RETRIES = 2                         # Number of retries for failed API requests
BACKOFF_FACTOR = 2                      # Delay multiplier between retries (e.g., 2, 4, 8 seconds)

# Only include coins in reports if they exceed this cumulative score threshold
CUMULATIVE_SCORE_REPORTING_THRESHOLD = 40

# Threading / performance
MAX_WORKERS = int(os.getenv('MAX_WORKERS', '8'))        # Thread pool size for coin processing
COIN_TIMEOUT = int(os.getenv('COIN_TIMEOUT', '120'))    # Per-coin processing timeout in seconds

# LLM configuration
LLM_PROVIDER = os.getenv('LLM_PROVIDER', 'openai')       # openai, anthropic, ollama, etc.
LLM_MODEL = os.getenv('LLM_MODEL', 'gpt-4.1')             # Model name for the chosen provider
LLM_API_KEY = os.getenv('OPENAI_API_KEY', '')             # API key (OPENAI_API_KEY for backwards compat)
LLM_BASE_URL = os.getenv('LLM_BASE_URL', '')              # Custom base URL (for Ollama, vLLM, etc.)

# Aurora PostgreSQL configuration (used to log or retrieve coin scores)
AURORA_HOST = os.getenv('AURORA_HOST')              # Database host endpoint
AURORA_PORT = int(os.getenv('AURORA_PORT', '5432'))   # Default port for PostgreSQL
AURORA_DB = os.getenv('AURORA_DB')                  # Name of the database
AURORA_USER = os.getenv('AURORA_USER')              # Database user
AURORA_PASSWORD = os.getenv('AURORA_PASSWORD')      # Database password

# CoinPaprika API key for fetching coin metadata and price data
COIN_PAPRIKA_API_KEY = os.getenv('COIN_PAPRIKA_API_KEY')

# Initialize the VADER sentiment analyzer (used to evaluate sentiment in news headlines/text)
analyzer = SentimentIntensityAnalyzer()

# ----------------------------
# Startup env var validation
# ----------------------------

_REQUIRED_VARS = {
    "COIN_PAPRIKA_API_KEY": COIN_PAPRIKA_API_KEY,

    "AURORA_HOST": AURORA_HOST,
    "AURORA_DB": AURORA_DB,
    "AURORA_USER": AURORA_USER,
    "AURORA_PASSWORD": AURORA_PASSWORD,
    "EMAIL_FROM": EMAIL_FROM,
    "EMAIL_TO": EMAIL_TO,
    "SMTP_SERVER": SMTP_SERVER,
    "SMTP_USERNAME": SMTP_USERNAME,
    "SMTP_PASSWORD": SMTP_PASSWORD,
}

_missing = [name for name, val in _REQUIRED_VARS.items() if not val]
if _missing:
    _logger.warning(
        "Missing environment variables (features that need them will fail): %s",
        ", ".join(_missing),
    )
