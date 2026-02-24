"""
Scrape all assets ranked by market cap from companiesmarketcap.com.

Usage:
    # Full scrape to CSV
    python -m ta_lab2.scripts.etl.scrape_assets_by_market_cap --out assets.csv

    # Refresh: scrape >= $25M and load directly to DB
    python -m ta_lab2.scripts.etl.scrape_assets_by_market_cap --min-mcap 25e6 --load-db

    # Both CSV and DB
    python -m ta_lab2.scripts.etl.scrape_assets_by_market_cap --min-mcap 25e6 --out assets.csv --load-db

Output: CSV with columns:
    rank, name, ticker, asset_type, market_cap, price, change_pct, country, url
"""

import argparse
import csv
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE_URL = "https://companiesmarketcap.com/assets-by-market-cap/"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

ASSET_TYPE_MAP = {
    "precious-metals-outliner": "precious_metal",
    "crypto-outliner": "crypto",
    "etf-outliner": "etf",
}

CSV_COLUMNS = [
    "rank",
    "name",
    "ticker",
    "asset_type",
    "market_cap",
    "price",
    "change_pct",
    "country",
    "url",
]


def _classify_asset_type(tr_tag) -> str:
    """Derive asset type from the CSS class on the <tr> element."""
    classes = tr_tag.get("class", [])
    for css_class, asset_type in ASSET_TYPE_MAP.items():
        if css_class in classes:
            return asset_type
    return "equity"


def _parse_number(text: str) -> float | None:
    """Parse a market-cap or price string like '$35.916 T' into a raw number."""
    if not text:
        return None
    text = text.strip().replace("$", "").replace(",", "")
    multipliers = {"T": 1e12, "B": 1e9, "M": 1e6, "K": 1e3}
    for suffix, mult in multipliers.items():
        if text.endswith(suffix):
            try:
                return float(text[:-1].strip()) * mult
            except ValueError:
                return None
    try:
        return float(text)
    except ValueError:
        return None


def _parse_pct(text: str) -> float | None:
    """Parse a percentage string like '-1.15%' or ' 1.02%' into a float."""
    if not text:
        return None
    text = text.strip().replace("%", "")
    try:
        return float(text)
    except ValueError:
        return None


def _parse_row(tr_tag) -> dict | None:
    """Extract one asset row from a <tr> element."""
    tds = tr_tag.find_all("td")
    if len(tds) < 5:
        return None

    # Rank (from data-sort attribute for reliability)
    rank_td = tds[0]
    rank = rank_td.get("data-sort")
    if rank is None:
        return None
    rank = int(rank)

    # Name and ticker
    name_td = tds[1]
    name_div = name_td.find("div", class_="company-name")
    code_div = name_td.find("div", class_="company-code")
    name = name_div.get_text(strip=True) if name_div else ""
    ticker = code_div.get_text(strip=True) if code_div else ""

    # Detail page URL
    link = name_td.find("a", href=True)
    url = f"https://companiesmarketcap.com{link['href']}" if link else ""

    # Asset type from row CSS class
    asset_type = _classify_asset_type(tr_tag)

    # Market cap (data-sort = raw cents/units)
    mcap_td = tds[2]
    market_cap = mcap_td.get("data-sort")
    if market_cap is not None:
        try:
            market_cap = int(market_cap)
        except ValueError:
            market_cap = _parse_number(mcap_td.get_text())
    else:
        market_cap = _parse_number(mcap_td.get_text())

    # Price (data-sort = price in cents)
    price_td = tds[3]
    price_raw = price_td.get("data-sort")
    if price_raw is not None:
        try:
            price = float(price_raw) / 100.0
        except ValueError:
            price = _parse_number(price_td.get_text())
    else:
        price = _parse_number(price_td.get_text())

    # Daily change %
    change_td = tds[4]
    change_raw = change_td.get("data-sort")
    if change_raw is not None:
        try:
            change_pct = float(change_raw) / 100.0
        except ValueError:
            change_pct = _parse_pct(change_td.get_text())
    else:
        change_pct = _parse_pct(change_td.get_text())

    # Country (last td, may be empty for crypto/metals)
    country_td = tds[-1]
    country_span = country_td.find("span", class_="responsive-hidden")
    country = country_span.get_text(strip=True) if country_span else ""

    return {
        "rank": rank,
        "name": name,
        "ticker": ticker,
        "asset_type": asset_type,
        "market_cap": market_cap,
        "price": price,
        "change_pct": change_pct,
        "country": country,
        "url": url,
    }


def scrape_page(page: int, session: requests.Session) -> list[dict]:
    """Scrape a single page of the assets-by-market-cap listing."""
    params = {"page": page} if page > 1 else {}
    resp = session.get(BASE_URL, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, "html.parser")
    rows = []
    for tr in soup.select("table tr"):
        row = _parse_row(tr)
        if row is not None:
            rows.append(row)
    return rows


def scrape_all(
    delay: float = 1.5,
    max_pages: int = 200,
    min_mcap: float | None = None,
) -> list[dict]:
    """Scrape all pages.

    Stops when:
      - a page returns zero data rows, OR
      - max_pages is reached, OR
      - min_mcap is set and the smallest market cap on the page falls below it
        (the full page is kept so no assets >= min_mcap are missed).
    """
    all_rows: list[dict] = []
    session = requests.Session()

    for page in range(1, max_pages + 1):
        try:
            rows = scrape_page(page, session)
        except requests.RequestException as e:
            logger.warning("Page %d failed: %s — stopping.", page, e)
            break

        if not rows:
            logger.info("Page %d returned 0 rows — done.", page)
            break

        all_rows.extend(rows)

        last_mcap = rows[-1].get("market_cap") or 0
        logger.info(
            "Page %3d: %3d rows (total %d, ranks %d–%d, last mcap $%s)",
            page,
            len(rows),
            len(all_rows),
            rows[0]["rank"],
            rows[-1]["rank"],
            f"{last_mcap:,.0f}",
        )

        # Stop after this page if the bottom row is below the floor
        if min_mcap is not None and last_mcap < min_mcap:
            logger.info(
                "Last row mcap $%s < floor $%s — stopping after page %d.",
                f"{last_mcap:,.0f}",
                f"{min_mcap:,.0f}",
                page,
            )
            break

        if page < max_pages:
            time.sleep(delay)

    return all_rows


def write_csv(rows: list[dict], path: Path) -> None:
    """Write scraped rows to a CSV file."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    logger.info("Wrote %d rows to %s", len(rows), path)


def main():
    parser = argparse.ArgumentParser(
        description="Scrape assets by market cap from companiesmarketcap.com"
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("assets_by_market_cap.csv"),
        help="Output CSV path (default: assets_by_market_cap.csv)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.5,
        help="Delay between page requests in seconds (default: 1.5)",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=200,
        help="Maximum pages to scrape (default: 200, auto-stops at empty page)",
    )
    parser.add_argument(
        "--min-mcap",
        type=float,
        default=None,
        help=(
            "Minimum market cap floor in dollars. Scraping stops after the page "
            "whose last row drops below this value. Rows below the floor are "
            "trimmed from output. Example: 25e6 for $25M."
        ),
    )
    parser.add_argument(
        "--load-db",
        action="store_true",
        help="Load scraped data directly into PostgreSQL (companiesmarketcap_assets table).",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    scraped_at = datetime.now(timezone.utc)

    mcap_label = f", min_mcap=${args.min_mcap:,.0f}" if args.min_mcap else ""
    logger.info(
        "Starting scrape (delay=%.1fs, max_pages=%d%s)",
        args.delay,
        args.max_pages,
        mcap_label,
    )
    rows = scrape_all(
        delay=args.delay,
        max_pages=args.max_pages,
        min_mcap=args.min_mcap,
    )

    if not rows:
        logger.error("No data scraped — exiting.")
        sys.exit(1)

    # Trim rows below the market cap floor (the last page may contain some)
    if args.min_mcap is not None:
        before = len(rows)
        rows = [r for r in rows if (r.get("market_cap") or 0) >= args.min_mcap]
        trimmed = before - len(rows)
        if trimmed:
            logger.info(
                "Trimmed %d rows below $%s floor.", trimmed, f"{args.min_mcap:,.0f}"
            )

    # Summary by asset type
    type_counts = {}
    for r in rows:
        type_counts[r["asset_type"]] = type_counts.get(r["asset_type"], 0) + 1
    logger.info("Asset type breakdown: %s", type_counts)

    write_csv(rows, args.out)
    logger.info("Done. %d assets scraped.", len(rows))

    # Optionally load directly to database
    if args.load_db:
        from ta_lab2.config import load_local_env
        from ta_lab2.io import get_engine
        from ta_lab2.scripts.etl.load_companiesmarketcap_assets import load_to_db

        load_local_env()
        engine = get_engine()
        loaded = load_to_db(rows, engine, scraped_at, min_mcap_floor=args.min_mcap)
        logger.info("Loaded %d rows to database.", loaded)


if __name__ == "__main__":
    main()
