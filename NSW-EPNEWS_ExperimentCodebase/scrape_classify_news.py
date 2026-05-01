#!/usr/bin/env python3
"""
Scrape WattClarity yearly article archives and classify each article into the
NSW-EPNews news CSV format.

Examples:
    OPENAI_API_KEY=... python3 scrape_classify_news.py --years 2025 2026
    DEEPSEEK_API_KEY=... python3 scrape_classify_news.py --provider deepseek --years 2025 2026
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup
from openai import OpenAI


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "CollectedData" / "Classified news"
BASE_ARCHIVE_URL = "https://wattclarity.com.au/articles/{year}/"
CSV_FIELDS = ["title", "author", "date", "topic", "classified_content"]
MARKET_KEYWORDS = [
    "aemo",
    "aemc",
    "aer",
    "ancillary",
    "battery",
    "blackout",
    "coal",
    "constraint",
    "demand",
    "dispatch",
    "direction",
    "drought",
    "energyconnect",
    "eraring",
    "fcas",
    "frequency",
    "generator",
    "grid",
    "interconnector",
    "intervention",
    "lor",
    "market demand",
    "market notice",
    "marginal",
    "mtpasa",
    "nem",
    "network",
    "nsw",
    "outage",
    "pasa",
    "peak",
    "power station",
    "price",
    "reserve",
    "rrp",
    "solar",
    "system strength",
    "transmission",
    "turbine",
    "unit",
    "weather",
    "wind",
]
PROVIDERS = {
    "openai": {
        "env": "OPENAI_API_KEY",
        "base_url": None,
        "model": "gpt-4o",
    },
    "deepseek": {
        "env": "DEEPSEEK_API_KEY",
        "base_url_env": "DEEPSEEK_BASE_URL",
        "model_env": "DEEPSEEK_MODEL",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
    },
}


CLASSIFICATION_PROMPT = """
You are an expert in electricity market analysis. Below is a news article with its title, date, topic and content.
Please generate a summary paragraph for it. The attributes that must be included in the paragraph are also provided below.
Your output should follow an exact format that I give you. Your response should not exceed 30000 characters.

1. Classification criteria:
  - Level 1 (Most Relevant): Extreme weather, turbine/generator failures, grid/system instability, fuel supply issues (coal, gas), coal-fired policies, gas pipeline failures.
  - Level 2 (Relevant): Grid frequency issues, fuel prices, coal mine accidents, market reactions.
  - Level 3 (Less Relevant): Energy policy, residential satisfaction, residential surveys.
2. Below is a list of attributes you MUST include in your paragraph
    summary: (the paragraph that summarized the new),
    relevance level: (Which level? Please classify its relevance to electricity prices according to the criteria given above),
    category: (which category in the relevance level?)
    Timeframe of the event impact on the electricity_market:,
    root_cause:,
    (below are additional fields, inferred from the news; if unavailable, write 'Unknown')
    accident scale:,
    dates (if different from the main date; if the same, repeat the same date):,
    affected region:,
    affected key users:,
    cause type:,
    causes (a summarized list of cause events):,
3. Please output your response in this format EXACTLY. You can reason your answer step by step. And after you generated your response, check if you mistake the new's post date and correct it if needed.:
    The summary of the news "{news title given to you}" posted at {news date given to you} is: {summary}; Its {other attribute 1} is: {your answer for that attribute}. Its {other attribute 2} is: {your answer for that attribute} .etc.
""".strip()


@dataclass
class Article:
    url: str
    title: str
    author: str
    date: str
    topic: str
    content: str


def get_soup(
    session: requests.Session,
    url: str,
    timeout: int = 30,
    retries: int = 3,
    retry_delay: float = 10.0,
) -> BeautifulSoup | None:
    for attempt in range(1, retries + 1):
        try:
            response = session.get(url, timeout=timeout)
        except requests.RequestException as exc:
            print(f"Unable to access page attempt {attempt}/{retries} ({exc}): {url}")
            if attempt < retries:
                time.sleep(retry_delay)
            continue
        if response.status_code == 200:
            return BeautifulSoup(response.text, "html.parser")
        print(f"Unable to access page attempt {attempt}/{retries} ({response.status_code}): {url}")
        if attempt < retries:
            time.sleep(retry_delay)
    return None


def archive_links(soup: BeautifulSoup) -> list[str]:
    article_links = soup.select("article.content-list h4.entry-title a")
    if not article_links:
        article_links = soup.select("article.content-list h3.entry-title.content-list-title a")
    return [a.get("href") for a in article_links if a.get("href")]


def next_page_url(soup: BeautifulSoup) -> str | None:
    next_link = soup.select_one("div.pagination a.next.page-numbers")
    return next_link.get("href") if next_link else None


def clean_date(raw_date_text: str) -> str:
    tokens = raw_date_text.split()
    if tokens and tokens[0].isalpha():
        raw_date_text = " ".join(tokens[1:])
    clean_text = re.sub(r"(\d+)(st|nd|rd|th)([A-Za-z])", r"\1 \3", raw_date_text)
    clean_text = re.sub(r"\s+", " ", clean_text).strip()
    try:
        date_obj = datetime.strptime(clean_text, "%d %B %Y %I:%M %p")
        return date_obj.strftime("%d-%m-%Y %I:%M:%S %p")
    except ValueError as exc:
        return "Date transformation fail: " + str(exc)


def parse_article_date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%d-%m-%Y %I:%M:%S %p")
    except ValueError:
        return None


def parse_bound(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.strptime(value, "%Y-%m-%d")


def market_relevant(article: Article) -> bool:
    haystack = f"{article.title}\n{article.topic}\n{article.content}".lower()
    return any(keyword in haystack for keyword in MARKET_KEYWORDS)


def article_text(soup: BeautifulSoup, selector: str, default: str) -> str:
    tag = soup.select_one(selector)
    return tag.get_text(strip=True) if tag else default


def fetch_article(
    session: requests.Session,
    url: str,
    retries: int,
    retry_delay: float,
) -> Article | None:
    soup = get_soup(session, url, retries=retries, retry_delay=retry_delay)
    if soup is None:
        return None

    article_content = soup.find("article") or soup.select_one(".entry-content") or soup.select_one(".post-content")
    if not article_content:
        print(f"Unable to extract article wrapper: {url}")
        return None

    title = article_text(soup, "h1.entry-title", "Can not find title")

    author_span = soup.find("span", class_="entry-meta-author")
    if author_span:
        author_link = author_span.find("a", class_="fn")
        author = author_link.get_text(strip=True) if author_link else author_span.get_text(strip=True)
    else:
        author = "Can not find author"

    date_span = soup.find("span", class_="entry-meta-date")
    date = clean_date(date_span.get_text(strip=True)) if date_span else "Can not find post time"

    topic_span = soup.find("span", class_="entry-meta-cats-name")
    if topic_span:
        topic_link = topic_span.find("a")
        topic = topic_link.get_text(strip=True) if topic_link else topic_span.get_text(strip=True)
    else:
        topic = "Can not find Topic"

    content_div = soup.find("div", class_="entry-content")
    content = content_div.get_text(separator="\n", strip=True) if content_div else "Can not find main text"
    content = re.sub(r"\s+", " ", content).strip()
    content = content.encode("utf-8", errors="replace").decode("utf-8")

    return Article(url=url, title=title, author=author, date=date, topic=topic, content=content)


def classify_article(
    client: OpenAI,
    model: str,
    article: Article,
    retries: int,
    retry_delay: float,
) -> str:
    prompt = (
        CLASSIFICATION_PROMPT
        + "\n\n"
        + f"Title:{article.title}, date:{article.date}, topic:{article.topic}, content:{article.content}"
    )
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            response = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=3000,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            last_error = exc
            print(f"Classification failed attempt {attempt}/{retries}: {article.title}: {exc}")
            if attempt < retries:
                time.sleep(retry_delay)
    raise RuntimeError(f"classification failed after {retries} attempts") from last_error


def existing_titles(csv_path: Path) -> set[str]:
    if not csv_path.exists():
        return set()
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        return {row["title"] for row in csv.DictReader(f) if row.get("title")}


def append_row(csv_path: Path, row: dict[str, str]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = csv_path.exists()
    with csv_path.open("a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def scrape_year(
    session: requests.Session,
    client: OpenAI | None,
    year: int,
    output_dir: Path,
    model: str,
    raw: bool,
    page_delay: float,
    article_delay: float,
    max_pages: int | None,
    max_articles: int | None,
    retries: int,
    retry_delay: float,
    start_date: datetime | None,
    end_date: datetime | None,
    market_prefilter: bool,
) -> None:
    output_path = output_dir / f"{year}_news.csv"
    seen_titles = existing_titles(output_path)
    current_url = BASE_ARCHIVE_URL.format(year=year)
    saved = 0
    skipped = 0

    print(f"======== {year} ========")
    page_count = 0
    while current_url:
        if max_pages is not None and page_count >= max_pages:
            print(f"Reached --max-pages={max_pages}.")
            break
        page_count += 1
        print(f"Fetching page: {current_url}")
        soup = get_soup(session, current_url, retries=retries, retry_delay=retry_delay)
        if soup is None:
            break

        links = archive_links(soup)
        if not links:
            print("No news found on this page, possibly the end.")
            break

        for link in links:
            if max_articles is not None and saved >= max_articles:
                print(f"Reached --max-articles={max_articles}.")
                current_url = None
                break
            article = fetch_article(session, link, retries=retries, retry_delay=retry_delay)
            if article is None:
                continue
            article_dt = parse_article_date(article.date)
            if article_dt is not None:
                if end_date is not None and article_dt.date() > end_date.date():
                    print(f"Skipped outside range after end date: {article.date}: {article.title}")
                    continue
                if start_date is not None and article_dt.date() < start_date.date():
                    print(f"Reached start date boundary at {article.date}: {article.title}")
                    current_url = None
                    break
            if article.title in seen_titles:
                skipped += 1
                print(f"Skipped existing: {article.title}")
                continue
            if market_prefilter and not market_relevant(article):
                skipped += 1
                print(f"Skipped by market prefilter: {article.title}")
                continue

            if raw:
                classified_content = article.content[:32000]
            else:
                if client is None:
                    raise RuntimeError("OPENAI_API_KEY is required unless --raw is used.")
                print(f"Classifying: {article.title}")
                try:
                    classified_content = classify_article(client, model, article, retries, retry_delay)
                except Exception as exc:
                    print(f"Skipped after classification failure: {article.title}: {exc}")
                    continue

            append_row(
                output_path,
                {
                    "title": article.title,
                    "author": article.author,
                    "date": article.date,
                    "topic": article.topic,
                    "classified_content": classified_content,
                },
            )
            seen_titles.add(article.title)
            saved += 1
            print(f"Saved to {output_path}: {article.title}")
            time.sleep(article_delay)

        current_url = next_page_url(soup)
        if current_url:
            time.sleep(page_delay)

    print(f"{year} done. saved={saved}, skipped_existing={skipped}, output={output_path}")


def parse_years(values: Iterable[str]) -> list[int]:
    years: list[int] = []
    for value in values:
        if "-" in value:
            start, end = value.split("-", 1)
            years.extend(range(int(start), int(end) + 1))
        else:
            years.append(int(value))
    return years


def main() -> int:
    parser = argparse.ArgumentParser(description="Scrape and classify WattClarity news for NSW-EPNews.")
    parser.add_argument("--years", nargs="+", required=True, help="Years or ranges, e.g. --years 2025 2026 or --years 2025-2026")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--provider", choices=sorted(PROVIDERS), default=os.getenv("LLM_PROVIDER", "openai"))
    parser.add_argument("--model", default=None, help="Override the provider default model.")
    parser.add_argument("--api-key", default=None, help="Optional API key override. Prefer environment variables.")
    parser.add_argument("--base-url", default=None, help="Optional OpenAI-compatible API base URL override.")
    parser.add_argument("--raw", action="store_true", help="Save raw article text instead of GPT classified_content.")
    parser.add_argument("--page-delay", type=float, default=2.0)
    parser.add_argument("--article-delay", type=float, default=1.0)
    parser.add_argument("--max-pages", type=int, default=None, help="Optional smoke-test limit per year.")
    parser.add_argument("--max-articles", type=int, default=None, help="Optional smoke-test limit per year.")
    parser.add_argument("--retries", type=int, default=3, help="Classification retry count per article.")
    parser.add_argument("--retry-delay", type=float, default=10.0, help="Seconds to wait between classification retries.")
    parser.add_argument("--start-date", default=None, help="Inclusive article date lower bound, YYYY-MM-DD.")
    parser.add_argument("--end-date", default=None, help="Inclusive article date upper bound, YYYY-MM-DD.")
    parser.add_argument(
        "--market-prefilter",
        action="store_true",
        help="Only classify articles whose title/topic/content contains electricity-market keywords.",
    )
    args = parser.parse_args()

    provider = PROVIDERS[args.provider]
    api_key = args.api_key or os.getenv(provider["env"])
    if not args.raw and not api_key:
        print(
            f"ERROR: set {provider['env']}, pass --api-key, or run with --raw to skip GPT classification.",
            file=sys.stderr,
        )
        return 2
    base_url = args.base_url if args.base_url is not None else os.getenv(provider.get("base_url_env", ""), provider["base_url"])
    model = args.model or os.getenv(provider.get("model_env", ""), provider["model"])
    client = None if args.raw else OpenAI(api_key=api_key, base_url=base_url)

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (compatible; NSW-EPNews research scraper; +https://wattclarity.com.au/)"
        }
    )
    start_date = parse_bound(args.start_date)
    end_date = parse_bound(args.end_date)

    for year in parse_years(args.years):
        scrape_year(
            session=session,
            client=client,
            year=year,
            output_dir=args.output_dir,
            model=model,
            raw=args.raw,
            page_delay=args.page_delay,
            article_delay=args.article_delay,
            max_pages=args.max_pages,
            max_articles=args.max_articles,
            retries=args.retries,
            retry_delay=args.retry_delay,
            start_date=start_date,
            end_date=end_date,
            market_prefilter=args.market_prefilter,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
