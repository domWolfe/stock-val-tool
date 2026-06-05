import os
import random
import requests
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
SEC_FRAMES_URL = "https://data.sec.gov/api/xbrl/frames/dei/EntityPublicFloat/USD/{period}.json"


def _sec_headers():
    """SEC requires a contact User-Agent on every request. Kept out of source via the SEC_API_USER_AGENT environment variable (e.g. "Name name@email.com")."""
    user_agent = os.environ.get("SEC_API_USER_AGENT")
    if not user_agent:
        raise RuntimeError(
            "SEC requests require a contact User-Agent. Set the SEC_API_USER_AGENT "
            "environment variable, e.g. 'Jane Doe jane@example.com'."
        )
    return {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"}


def _recent_periods(years_back=4):
    """Instantaneous frame ids (e.g. 'CY2024Q4I') for the last few years.
    Filers report at different times, so we sweep several and keep the newest."""

    end_year = 2025
    periods = []
    for year in range(end_year - years_back, end_year + 1):
        for quarter in (1, 2, 3, 4):
            periods.append(f"CY{year}Q{quarter}I")
    return periods


def _fetch_public_floats(headers):
    """Return {cik: public_float}, newest reported value winning."""
    floats = {}
    for period in _recent_periods():
        response = requests.get(SEC_FRAMES_URL.format(period=period), headers=headers, timeout=30)
        if response.status_code != 200:
            continue
        for row in response.json().get("data", []):
            floats[row["cik"]] = row["val"]
    return floats


def generate_ticker_file(output_file="tickers.txt", min_market_cap=1_000_000_000, target_count=1000, random_seed=42) -> list:
    """
    Generate a text file of randomly selected stock tickers above a market-cap
    threshold, sourced entirely from SEC XBRL data (no per-ticker Yahoo lookups).

    Parameters:
    output_file : str, default "tickers.txt"
        The filename for the output text file.
    min_market_cap : int, default 1,000,000,000
        Minimum market cap (approximated by SEC EntityPublicFloat) in USD.
    target_count : int, default 1000
        Number of unique, valid tickers to sample and return.
    random_seed : int, default 42
        Seed for reproducible sampling.

    Returns:
    list
        The selected stock ticker strings.

    Raises:
    RuntimeError
        If the SEC_API_USER_AGENT environment variable is not set.
    ValueError
        If no tickers meet the market-cap threshold.
    """
    headers = _sec_headers()

    tickers_payload = requests.get(SEC_TICKERS_URL, headers=headers, timeout=30).json()
    cik_to_ticker = {
        entry["cik_str"]: entry["ticker"]
        for entry in tickers_payload.values()
        if entry["ticker"].isalpha()
    }

    public_floats = _fetch_public_floats(headers)

    candidates = {
        cik_to_ticker[cik]
        for cik, public_float in public_floats.items()
        if public_float and public_float >= min_market_cap and cik in cik_to_ticker
    }

    selected = sorted(candidates)
    random.seed(random_seed)
    random.shuffle(selected)
    selected = selected[:target_count]

    if not selected:
        raise ValueError(f"No tickers met the market cap threshold of ${min_market_cap:,}")

    output_dir = Path("training_data")
    output_dir.mkdir(exist_ok=True)
    path = output_dir / output_file

    with open(path, "w") as f:
        for ticker in selected:
            f.write(f"{ticker}\n")

    return selected
