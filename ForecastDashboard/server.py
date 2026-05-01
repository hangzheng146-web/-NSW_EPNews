#!/usr/bin/env python3
"""Local forecast dashboard server.

Provides:
- static dashboard files
- /api/forecast?forecast_start=YYYY-MM-DD

The server fetches AEMO price data live when possible. BoM dailyDataFile pages
are also attempted live and merged with local curated temperature CSVs as fallback.
"""

from __future__ import annotations

import io
import csv
import json
import math
import mimetypes
import os
import re
import subprocess
import sys
import urllib.parse
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import requests


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[0]
MODEL_DIR = ROOT / "ModelTraining_7day" / "models"
TEMP_DIR = ROOT / "CollectedData" / "Temperature"
PRICE_LOCAL = ROOT / "CollectedData" / "Electricity prices from NEM" / "unified_price_data" / "unified_used_for_experiment" / "2015To2026Data.csv"
BATTERY_OUTPUT_DIR = ROOT / "BatteryStrategy" / "outputs"
BATTERY_RUN_ROOT = ROOT / "BatteryStrategy" / "runs"
BATTERY_SCRIPT = ROOT / "BatteryStrategy" / "run_battery_strategy.py"

LOW_THRESHOLD = 30
HIGH_THRESHOLD = 150
SPIKE_THRESHOLD = 300

BOM_PAGE_URLS = {
    "max_66194": "https://www.bom.gov.au/jsp/ncc/cdio/weatherData/av?p_display_type=dailyDataFile&p_nccObsCode=122&p_stn_num=066194",
    "max_66037": "https://www.bom.gov.au/jsp/ncc/cdio/weatherData/av?p_display_type=dailyDataFile&p_nccObsCode=122&p_stn_num=066037",
    "min_66194": "https://www.bom.gov.au/jsp/ncc/cdio/weatherData/av?p_display_type=dailyDataFile&p_nccObsCode=123&p_stn_num=066194",
    "min_66037": "https://www.bom.gov.au/jsp/ncc/cdio/weatherData/av?p_display_type=dailyDataFile&p_nccObsCode=123&p_stn_num=066037",
}

MONTH_NAME_TO_NUM = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}

_MODEL_CACHE = None
_LOCAL_PRICE_CACHE = None
_TEMP_CACHE = None
_LIVE_TEMP_CACHE = None


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables: list[list[list[str]]] = []
        self._current_table: list[list[str]] | None = None
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._current_table = []
        elif tag == "tr" and self._current_table is not None:
            self._current_row = []
        elif tag in {"td", "th"} and self._current_row is not None:
            self._current_cell = []

    def handle_data(self, data):
        if self._current_cell is not None:
            self._current_cell.append(data)

    def handle_endtag(self, tag):
        if tag in {"td", "th"} and self._current_cell is not None and self._current_row is not None:
            self._current_row.append(" ".join(part.strip() for part in self._current_cell if part.strip()))
            self._current_cell = None
        elif tag == "tr" and self._current_row is not None and self._current_table is not None:
            if self._current_row:
                self._current_table.append(self._current_row)
            self._current_row = None
        elif tag == "table" and self._current_table is not None:
            self.tables.append(self._current_table)
            self._current_table = None


def html_tables(text: str) -> list[pd.DataFrame]:
    parser = TableParser()
    parser.feed(text)
    tables = []
    for rows in parser.tables:
        if len(rows) < 2:
            continue
        width = len(rows[0])
        body = [row for row in rows[1:] if len(row) == width]
        if body:
            tables.append(pd.DataFrame(body, columns=rows[0]))
    return tables


def best_model_artifact() -> tuple[str, Path]:
    candidates: list[tuple[str, float, Path]] = []
    gbdt = MODEL_DIR / "gbdt_long_training_summary.json"
    news = MODEL_DIR / "gbdt_long_news_training_summary.json"
    if gbdt.exists():
        payload = json.loads(gbdt.read_text())
        for name in ("LightGBM", "XGBoost"):
            if name in payload["metrics"] and name in payload["artifacts"]:
                artifact_path = Path(payload["artifacts"][name])
                if not artifact_path.exists():
                    artifact_path = MODEL_DIR / artifact_path.name
                candidates.append((name, payload["metrics"][name]["MAE"], artifact_path))
    if news.exists():
        payload = json.loads(news.read_text())
        for name in ("LightGBM_news", "XGBoost_news"):
            if name in payload["metrics"] and name in payload["artifacts"]:
                artifact_path = Path(payload["artifacts"][name])
                if not artifact_path.exists():
                    artifact_path = MODEL_DIR / artifact_path.name
                candidates.append((name, payload["metrics"][name]["MAE"], artifact_path))
    if not candidates:
        raise FileNotFoundError("No trained LightGBM/XGBoost model summaries found")
    name, _, path = sorted(candidates, key=lambda item: item[1])[0]
    return name, path


def load_model():
    global _MODEL_CACHE
    if _MODEL_CACHE is None:
        name, path = best_model_artifact()
        artifact = joblib.load(path)
        _MODEL_CACHE = (name, artifact["model"], artifact["feature_names"], path)
    return _MODEL_CACHE


def month_range(start: date, end: date) -> list[tuple[int, int]]:
    months = []
    current = date(start.year, start.month, 1)
    while current <= end:
        months.append((current.year, current.month))
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
    return months


def fetch_aemo_month(year: int, month: int) -> pd.DataFrame:
    url = f"https://www.aemo.com.au/aemo/data/nem/priceanddemand/PRICE_AND_DEMAND_{year}{month:02d}_NSW1.csv"
    response = requests.get(url, timeout=20)
    response.raise_for_status()
    df = pd.read_csv(io.StringIO(response.text), parse_dates=["SETTLEMENTDATE"])
    return df[df["REGION"] == "NSW1"].copy()


def aemo_month_url(year: int, month: int) -> str:
    return f"https://www.aemo.com.au/aemo/data/nem/priceanddemand/PRICE_AND_DEMAND_{year}{month:02d}_NSW1.csv"


def downsample_30min(df: pd.DataFrame) -> pd.DataFrame:
    frame = df.copy()
    frame.set_index("SETTLEMENTDATE", inplace=True)
    out = frame.resample("30min", label="right", closed="right").agg(
        {"RRP": "median", "TOTALDEMAND": "mean", "REGION": "first", "PERIODTYPE": "first"}
    )
    out.dropna(subset=["RRP"], inplace=True)
    out.reset_index(inplace=True)
    return out


def read_local_prices() -> pd.DataFrame:
    global _LOCAL_PRICE_CACHE
    if _LOCAL_PRICE_CACHE is None:
        df = pd.read_csv(PRICE_LOCAL)
        df = df[df["REGION"] == "NSW1"].copy()
        df["SETTLEMENTDATE"] = pd.to_datetime(df["SETTLEMENTDATE"], dayfirst=True, errors="raise")
        _LOCAL_PRICE_CACHE = df
    return _LOCAL_PRICE_CACHE.copy()


def price_history(forecast_start: date, warnings: list[str]) -> np.ndarray:
    hist_start = forecast_start - timedelta(days=28)
    hist_end = forecast_start - timedelta(minutes=30)
    months = month_range(hist_start, forecast_start)
    try:
        frames = [fetch_aemo_month(y, m) for y, m in months]
        prices = downsample_30min(pd.concat(frames, ignore_index=True))
        source = "AEMO live monthly CSV"
    except Exception as exc:
        warnings.append("AEMO 实时电价抓取失败，已使用本地数据和缺失填充")
        prices = read_local_prices()
        source = "local 2015To2026Data.csv"

    mask = (prices["SETTLEMENTDATE"] >= pd.Timestamp(hist_start)) & (prices["SETTLEMENTDATE"] <= pd.Timestamp(hist_end))
    selected = prices.loc[mask].copy()
    selected["date"] = selected["SETTLEMENTDATE"].dt.date
    selected["time"] = selected["SETTLEMENTDATE"].dt.strftime("%H:%M")
    expected_times = [f"{h:02d}:{m:02d}" for h in range(24) for m in (0, 30)]
    pivot = selected.pivot_table(index="date", columns="time", values="RRP", aggfunc="last").reindex(columns=expected_times)
    expected_dates = pd.date_range(hist_start, forecast_start - timedelta(days=1), freq="D").date
    pivot = pivot.reindex(expected_dates)
    if pivot.isna().any().any():
        missing_count = int(pivot.isna().sum().sum())
        pivot = pivot.ffill().bfill()
        warnings.append(f"历史电价有 {missing_count} 个半小时点缺失，已用相邻日期同一时段价格填充")
    if pivot.isna().any().any():
        raise ValueError("历史 28 天电价不足，无法组成 28×48 输入矩阵")
    if source == "AEMO live monthly CSV":
        urls = ", ".join(aemo_month_url(y, m) for y, m in months)
        warnings.append(f"电价来源：{source}；抓取文件：{urls}")
    else:
        warnings.append(f"电价来源：{source}")
    return pivot.to_numpy(dtype=np.float32)


def load_local_temperature() -> pd.DataFrame:
    global _TEMP_CACHE
    if _TEMP_CACHE is not None:
        return _TEMP_CACHE.copy()
    max_df = pd.read_csv(TEMP_DIR / "max_temps_2015_2026.csv")
    min_df = pd.read_csv(TEMP_DIR / "min_temps_2015_2026.csv")
    max_df["date"] = pd.to_datetime(max_df[["Year", "Month", "Day"]]).dt.date
    min_df["date"] = pd.to_datetime(min_df[["Year", "Month", "Day"]]).dt.date
    max_daily = max_df.groupby("date")["Maximum temperature (Degree C)"].mean().rename("max_temp")
    min_daily = min_df.groupby("date")["Minimum temperature (Degree C)"].mean().rename("min_temp")
    _TEMP_CACHE = pd.concat([max_daily, min_daily], axis=1).sort_index()
    return _TEMP_CACHE.copy()


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out.columns = [str(col).replace("\ufeff", "").strip() for col in out.columns]
    return out


def pick_bom_table(tables: list[pd.DataFrame], value_column: str) -> pd.DataFrame:
    for table in tables:
        df = normalize_columns(table)
        if {"Year", "Month", "Day", value_column}.issubset(df.columns):
            return df
    raise ValueError(f"页面中没有找到包含 Year/Month/Day/{value_column} 的温度表")


def extract_bom_year(text: str) -> int:
    match = re.search(r"\bYear\s*:?\s*(20\d{2}|19\d{2})\b", text, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    years = [int(value) for value in re.findall(r"\b(20\d{2}|19\d{2})\b", text)]
    if years:
        return max(years)
    return date.today().year


def parse_ordinal_day(value: str) -> int | None:
    match = re.search(r"\b([1-9]|[12]\d|3[01])(?:st|nd|rd|th)?\b", str(value).strip(), flags=re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def parse_temperature_cell(value: str) -> float | None:
    text = str(value).strip()
    if not text or text in {"-", "--"}:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    parsed = float(match.group(0))
    if -30 <= parsed <= 60:
        return parsed
    return None


def rows_to_month_grid_values(rows: list[list[str]], year: int, value_column: str) -> pd.DataFrame:
    records = []
    for header_idx, header in enumerate(rows):
        month_columns = []
        for col_idx, cell in enumerate(header):
            normalized = re.sub(r"[^A-Za-z]", "", str(cell)).lower()
            if normalized in MONTH_NAME_TO_NUM:
                month_columns.append((col_idx, MONTH_NAME_TO_NUM[normalized]))
        if len(month_columns) < 3:
            continue
        for row in rows[header_idx + 1 :]:
            if not row:
                continue
            day = parse_ordinal_day(row[0])
            if day is None:
                continue
            for col_idx, month in month_columns:
                if col_idx >= len(row):
                    continue
                value = parse_temperature_cell(row[col_idx])
                if value is None:
                    continue
                try:
                    record_date = date(year, month, day)
                except ValueError:
                    continue
                records.append({"date": record_date, value_column: value})
    return pd.DataFrame(records).drop_duplicates(subset=["date"], keep="last")


def parse_bom_month_grid(text: str, value_column: str) -> pd.DataFrame:
    year = extract_bom_year(text)
    parser = TableParser()
    parser.feed(text)
    for rows in parser.tables:
        df = rows_to_month_grid_values(rows, year, value_column)
        if not df.empty:
            return df
    return pd.DataFrame()


def rows_to_daily_values(rows: list[list[str]], value_column: str) -> pd.DataFrame:
    records = []
    for row in rows:
        cells = [cell.strip() for cell in row if str(cell).strip()]
        if len(cells) < 4:
            continue
        for idx, cell in enumerate(cells):
            if not re.fullmatch(r"\d{4}", cell):
                continue
            year = int(cell)
            if year < 1900 or year > 2100 or idx + 3 >= len(cells):
                continue
            try:
                month = int(float(cells[idx + 1]))
                day = int(float(cells[idx + 2]))
            except ValueError:
                continue
            if not (1 <= month <= 12 and 1 <= day <= 31):
                continue
            value = None
            for candidate in cells[idx + 3 :]:
                try:
                    parsed = float(candidate)
                except ValueError:
                    continue
                if -30 <= parsed <= 60:
                    value = parsed
                    break
            if value is None:
                continue
            records.append({"date": date(year, month, day), value_column: value})
            break
    return pd.DataFrame(records)


def parse_bom_daily_values(text: str, value_column: str) -> pd.DataFrame:
    parser = TableParser()
    parser.feed(text)
    rows = [row for table in parser.tables for row in table]
    df = rows_to_daily_values(rows, value_column)
    if not df.empty:
        return df

    text_rows = []
    for line in re.split(r"[\r\n]+", re.sub(r"<[^>]+>", " ", text)):
        values = re.findall(r"-?\d+(?:\.\d+)?", line)
        if len(values) >= 4:
            text_rows.append(values)
    return rows_to_daily_values(text_rows, value_column)


def fetch_bom_page_data(label: str, url: str, value_column: str) -> pd.DataFrame:
    headers = {"User-Agent": "Mozilla/5.0"}
    response = requests.get(url, headers=headers, timeout=20)
    response.raise_for_status()
    text = response.text
    lower_text = text.lower()
    if (
        "your access is blocked" in lower_text
        or "does not support web scraping" in lower_text
        or "potential automated access request" in lower_text
        or "screenscraper" in lower_text
    ):
        raise PermissionError("BoM 页面禁止自动访问")
    if "Product code" in text and value_column in text:
        df = normalize_columns(pd.read_csv(io.StringIO(text)))
    else:
        tables = html_tables(text)
        try:
            df = pick_bom_table(tables, value_column)
        except ValueError:
            df = parse_bom_month_grid(text, value_column)
            if df.empty:
                df = parse_bom_daily_values(text, value_column)
    if {"Year", "Month", "Day"}.issubset(df.columns):
        df["date"] = pd.to_datetime(df[["Year", "Month", "Day"]], errors="coerce").dt.date
    if "date" not in df.columns:
        raise ValueError(f"{label} 没有读到有效年月日")
    if value_column not in df.columns:
        raise ValueError(f"{label} 没有读到温度数值")
    if df[value_column].notna().sum() == 0:
        raise ValueError(f"{label} 没有读到有效温度数值")
    return df.dropna(subset=["date", value_column])[["date", value_column]]


def load_live_bom_temperature(warnings: list[str]) -> pd.DataFrame | None:
    global _LIVE_TEMP_CACHE
    if _LIVE_TEMP_CACHE is not None:
        warnings.append("温度来源：BoM dailyDataFile 页面")
        return _LIVE_TEMP_CACHE.copy()
    try:
        max_frames = [
            fetch_bom_page_data("max_66194", BOM_PAGE_URLS["max_66194"], "Maximum temperature (Degree C)"),
            fetch_bom_page_data("max_66037", BOM_PAGE_URLS["max_66037"], "Maximum temperature (Degree C)"),
        ]
        min_frames = [
            fetch_bom_page_data("min_66194", BOM_PAGE_URLS["min_66194"], "Minimum temperature (Degree C)"),
            fetch_bom_page_data("min_66037", BOM_PAGE_URLS["min_66037"], "Minimum temperature (Degree C)"),
        ]
    except Exception as exc:
        warnings.append(f"BoM dailyDataFile 实时温度读取失败，使用本地温度文件回退：{exc}")
        return None

    max_daily = pd.concat(max_frames).groupby("date")["Maximum temperature (Degree C)"].mean().rename("max_temp")
    min_daily = pd.concat(min_frames).groupby("date")["Minimum temperature (Degree C)"].mean().rename("min_temp")
    _LIVE_TEMP_CACHE = pd.concat([max_daily, min_daily], axis=1).sort_index()
    warnings.append("温度来源：BoM dailyDataFile 页面")
    return _LIVE_TEMP_CACHE.copy()


def load_temperature(warnings: list[str]) -> pd.DataFrame:
    local = load_local_temperature()
    live = load_live_bom_temperature(warnings)
    if live is None:
        warnings.append("温度来源：本地 max_temps_2015_2026.csv / min_temps_2015_2026.csv")
        return local
    combined = local.combine_first(live)
    combined.update(live)
    return combined.sort_index()


def temperature_features(forecast_start: date, warnings: list[str]) -> tuple[np.ndarray, np.ndarray]:
    temp = load_temperature(warnings)
    hist_dates = pd.date_range(forecast_start - timedelta(days=28), forecast_start - timedelta(days=1), freq="D").date
    future_dates = pd.date_range(forecast_start, forecast_start + timedelta(days=6), freq="D").date
    hist = temp.reindex(hist_dates)
    if hist.isna().any().any():
        missing_days = [str(day) for day in hist.index[hist.isna().any(axis=1)]]
        hist = hist.ffill().bfill()
        warnings.append(f"历史温度缺失 {len(missing_days)} 天，已用最近可用温度填充：{', '.join(missing_days[:3])}")
    if hist.isna().any().any():
        raise ValueError("历史 28 天温度不足")
    future = temp.reindex(future_dates)
    if future.isna().any().any():
        last = temp.dropna().iloc[-7:]
        fill_max = float(last["max_temp"].mean())
        fill_min = float(last["min_temp"].mean())
        future["max_temp"] = future["max_temp"].fillna(fill_max)
        future["min_temp"] = future["min_temp"].fillna(fill_min)
        warnings.append("未来温度缺失，已用最近 7 天观测均值填充；真实预测应替换为天气预报")
    return hist[["max_temp", "min_temp"]].to_numpy(dtype=np.float32), future[["max_temp", "min_temp"]].to_numpy(dtype=np.float32)


def build_feature_rows(hist_price: np.ndarray, hist_temp: np.ndarray, future_temp: np.ndarray) -> np.ndarray:
    rows = []
    periods = 48
    for day_idx in range(7):
        for slot in range(48):
            values = []
            recent = hist_price[-7:, slot]
            values.extend(recent.tolist())
            same_slot = hist_price[:, slot]
            values.extend([same_slot.mean(), same_slot.std(), same_slot.min(), same_slot.max()])
            last_day = hist_price[-1, :]
            values.extend([last_day.mean(), last_day.min(), last_day.max(), last_day.std()])
            hist_max = hist_temp[:, 0]
            hist_min = hist_temp[:, 1]
            hist_avg = (hist_max + hist_min) / 2
            values.extend([hist_max.mean(), hist_max[-1], hist_min.mean(), hist_min[-1], hist_avg.mean(), hist_avg[-1]])
            fmax, fmin = future_temp[day_idx]
            values.extend([fmax, fmin, (fmax + fmin) / 2])
            slot_angle = 2 * math.pi * slot / periods
            day_angle = 2 * math.pi * day_idx / 7
            values.extend([day_idx + 1, slot, math.sin(slot_angle), math.cos(slot_angle), math.sin(day_angle), math.cos(day_angle)])
            rows.append(values)
    return np.asarray(rows, dtype=np.float32)


def forecast_payload(forecast_start: date) -> dict:
    warnings: list[str] = []
    model_name, model, feature_names, model_path = load_model()
    hist_price = price_history(forecast_start, warnings)
    hist_temp, future_temp = temperature_features(forecast_start, warnings)
    x = build_feature_rows(hist_price, hist_temp, future_temp)
    pred = model.predict(x).astype(float).reshape(7, 48)

    points = []
    for day in range(7):
        current_date = forecast_start + timedelta(days=day)
        for slot in range(48):
            ts = datetime.combine(current_date, datetime.min.time()) + timedelta(minutes=30 * slot)
            points.append(
                {
                    "timestamp": ts.strftime("%Y-%m-%d %H:%M"),
                    "date": current_date.strftime("%Y-%m-%d"),
                    "half_hour_index": slot,
                    "predicted_price": round(float(pred[day, slot]), 2),
                }
            )
    return {
        "metadata": {
            "region": "NSW1",
            "forecast_start": forecast_start.strftime("%Y-%m-%d"),
            "forecast_days": 7,
            "frequency": "30min",
            "model_name": f"{model_name}-7D-30min",
            "model_artifact": str(model_path),
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "warnings": warnings,
        },
        "thresholds": {
            "low_price_threshold": LOW_THRESHOLD,
            "high_price_threshold": HIGH_THRESHOLD,
            "spike_threshold": SPIKE_THRESHOLD,
        },
        "point_forecast": points,
    }


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with open(path, "r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def metric_map(rows: list[dict[str, str]], key_name: str = "metric") -> dict[str, dict[str, str]]:
    return {row[key_name]: row for row in rows if row.get(key_name)}


def numeric(value: str | None, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        return float(value)
    except ValueError:
        return default


def battery_strategy_files(output_dir: Path) -> dict[str, Path]:
    return {
        "battery_parameters": output_dir / "battery_parameters.csv",
        "price_forecast_used": output_dir / "price_forecast_used.csv",
        "battery_dispatch_result": output_dir / "battery_dispatch_result.csv",
        "soc_curve": output_dir / "soc_curve.csv",
        "revenue_summary": output_dir / "revenue_summary.csv",
        "validation_checks": output_dir / "validation_checks.txt",
        "run_metadata": output_dir / "run_metadata.json",
    }


def battery_strategy_payload(output_dir: Path = BATTERY_OUTPUT_DIR, forecast_start: str | None = None) -> dict:
    files = battery_strategy_files(output_dir)
    required = {name: path for name, path in files.items() if name != "run_metadata"}
    missing = [name for name, path in required.items() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"BatteryStrategy 输出文件缺失：{', '.join(missing)}")

    params = read_csv_rows(files["battery_parameters"])
    price = read_csv_rows(files["price_forecast_used"])
    dispatch = read_csv_rows(files["battery_dispatch_result"])
    soc = read_csv_rows(files["soc_curve"])
    revenue = read_csv_rows(files["revenue_summary"])
    validation = files["validation_checks"].read_text(encoding="utf-8")
    run_metadata = json.loads(files["run_metadata"].read_text(encoding="utf-8")) if files["run_metadata"].exists() else {}
    revenue_by_metric = metric_map(revenue)

    actual_charge = [row for row in dispatch if numeric(row.get("charge_mwh_grid")) > 0]
    actual_discharge = [row for row in dispatch if numeric(row.get("discharge_mwh_grid")) > 0]
    actual_idle = [
        row
        for row in dispatch
        if numeric(row.get("charge_mwh_grid")) <= 0 and numeric(row.get("discharge_mwh_grid")) <= 0
    ]
    spike_rows = [row for row in dispatch if row.get("spike_risk") == "True"]
    net_revenue = numeric(revenue_by_metric.get("total_net_revenue", {}).get("value"))
    generated_at = run_metadata.get("finished_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return {
        "metadata": {
            "forecast_start": forecast_start,
            "run_id": run_metadata.get("run_id"),
            "source_directory": str(output_dir),
            "generated_at": generated_at,
            "files": {name: str(path) for name, path in files.items()},
            "run_metadata": run_metadata,
        },
        "parameters": params,
        "revenue_summary": revenue,
        "validation_text": validation,
        "validation_status": "PASS" if "status: PASS" in validation else "FAIL",
        "counts": {
            "forecast_points": len(price),
            "dispatch_rows": len(dispatch),
            "soc_rows": len(soc),
            "actual_charge_intervals": len(actual_charge),
            "actual_discharge_intervals": len(actual_discharge),
            "actual_idle_intervals": len(actual_idle),
            "spike_risk_intervals": len(spike_rows),
        },
        "interpretation": {
            "net_revenue_aud": net_revenue,
            "message": "净收益为负：本次规则触发了充电，但没有触发高价放电，因此只有充电成本没有放电收入。"
            if net_revenue < 0
            else "净收益非负：本次规则策略产生了放电收入或充电成本较低。",
        },
        "tables": {
            "price_forecast_used": price[:24],
            "battery_dispatch_result": dispatch[:48],
            "soc_curve": soc,
        },
    }


def run_battery_strategy_for_date(forecast_start: date, forecast_base_url: str | None = None) -> dict:
    forecast_value = forecast_start.strftime("%Y-%m-%d")
    run_id = forecast_value
    output_dir = BATTERY_RUN_ROOT / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    base_url = (forecast_base_url or f"http://127.0.0.1:{os.environ.get('PORT', '8765')}").rstrip("/")
    forecast_url = f"{base_url}/api/forecast?forecast_start={forecast_value}"
    command = [
        sys.executable,
        str(BATTERY_SCRIPT),
        "--forecast-json",
        forecast_url,
        "--output-dir",
        str(output_dir),
    ]
    completed = subprocess.run(
        command,
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        timeout=180,
        check=False,
    )
    run_log = {
        "run_id": run_id,
        "forecast_start": forecast_value,
        "output_directory": str(output_dir),
        "forecast_url": forecast_url,
        "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "command": " ".join(command),
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }
    if completed.returncode != 0:
        raise RuntimeError(f"Battery strategy run failed: {completed.stderr or completed.stdout}")
    run_log["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    (output_dir / "run_metadata.json").write_text(json.dumps(run_log, indent=2), encoding="utf-8")
    payload = battery_strategy_payload(output_dir=output_dir, forecast_start=forecast_value)
    return payload


def ensure_default_battery_strategy_run() -> None:
    today = date.today()
    output_dir = BATTERY_RUN_ROOT / today.strftime("%Y-%m-%d")
    files = battery_strategy_files(output_dir)
    required = [files["battery_parameters"], files["price_forecast_used"], files["battery_dispatch_result"], files["soc_curve"], files["revenue_summary"], files["validation_checks"], files["run_metadata"]]
    if all(path.exists() for path in required):
        return
    try:
        run_battery_strategy_for_date(today)
    except Exception as exc:
        print(f"Warning: default battery strategy warm-up skipped: {exc}")


class Handler(SimpleHTTPRequestHandler):
    def service_base_url(self) -> str:
        scheme = self.headers.get("X-Forwarded-Proto", "http")
        host = self.headers.get("Host")
        if host:
            return f"{scheme}://{host}"
        port = os.environ.get("PORT", "8765")
        return f"http://127.0.0.1:{port}"

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/forecast":
            qs = urllib.parse.parse_qs(parsed.query)
            value = qs.get("forecast_start", [date.today().strftime("%Y-%m-%d")])[0]
            try:
                start = datetime.strptime(value, "%Y-%m-%d").date()
                payload = forecast_payload(start)
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                body = json.dumps({"error": str(exc)}).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            return
        if parsed.path == "/api/battery-strategy":
            try:
                payload = battery_strategy_payload()
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                body = json.dumps({"error": str(exc)}).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            return
        if parsed.path == "/api/battery-strategy/run":
            qs = urllib.parse.parse_qs(parsed.query)
            value = qs.get("forecast_start", [date.today().strftime("%Y-%m-%d")])[0]
            try:
                start = datetime.strptime(value, "%Y-%m-%d").date()
                payload = run_battery_strategy_for_date(start, forecast_base_url=self.service_base_url())
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except Exception as exc:
                body = json.dumps({"error": str(exc)}).encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            return
        return super().do_GET()


def main() -> int:
    mimetypes.add_type("text/javascript", ".js")
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8765"))
    ensure_default_battery_strategy_run()
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Forecast dashboard: http://{host}:{port}/index.html")
    server.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
