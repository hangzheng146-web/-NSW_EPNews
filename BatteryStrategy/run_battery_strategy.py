#!/usr/bin/env python3
"""Rule-based battery arbitrage prototype.

This script does not run or change the forecasting pipeline. It consumes an
existing 7-day forecast JSON with `point_forecast` and writes dispatch outputs.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import urllib.request
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FORECAST_JSON = ROOT / "ForecastDashboard" / "forecast_sample.json"
DEFAULT_OUTPUT_DIR = ROOT / "BatteryStrategy" / "outputs"


@dataclass(frozen=True)
class BatteryParameters:
    capacity_mwh: float = 100.0
    max_charge_power_mw: float = 50.0
    max_discharge_power_mw: float = 50.0
    initial_soc_mwh: float = 50.0
    min_soc_mwh: float = 10.0
    max_soc_mwh: float = 90.0
    charge_efficiency: float = 0.95
    discharge_efficiency: float = 0.95
    cycle_cost_aud_per_mwh: float = 10.0
    interval_hours: float = 0.5
    low_price_threshold: float = 30.0
    high_price_threshold: float = 150.0
    spike_price_threshold: float = 300.0


PARAM_UNITS = {
    "capacity_mwh": "MWh",
    "max_charge_power_mw": "MW",
    "max_discharge_power_mw": "MW",
    "initial_soc_mwh": "MWh",
    "min_soc_mwh": "MWh",
    "max_soc_mwh": "MWh",
    "charge_efficiency": "ratio",
    "discharge_efficiency": "ratio",
    "cycle_cost_aud_per_mwh": "AUD/MWh",
    "interval_hours": "hour",
    "low_price_threshold": "AUD/MWh",
    "high_price_threshold": "AUD/MWh",
    "spike_price_threshold": "AUD/MWh",
}


def load_forecast(source: str) -> dict[str, Any]:
    if source.startswith(("http://", "https://")):
        with urllib.request.urlopen(source, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    with open(source, "r", encoding="utf-8") as handle:
        return json.load(handle)


def parse_points(payload: dict[str, Any]) -> list[dict[str, Any]]:
    points = payload.get("point_forecast", [])
    if not isinstance(points, list) or not points:
        raise ValueError("forecast JSON must contain a non-empty point_forecast list")
    parsed = []
    for idx, point in enumerate(points):
        timestamp = point.get("timestamp")
        price = point.get("predicted_price")
        if timestamp is None or price is None:
            raise ValueError(f"point_forecast[{idx}] missing timestamp or predicted_price")
        parsed.append(
            {
                "timestamp": str(timestamp),
                "date": str(point.get("date", str(timestamp)[:10])),
                "half_hour_index": int(point.get("half_hour_index", idx % 48)),
                "predicted_price": float(price),
            }
        )
    parsed.sort(key=lambda row: datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M"))
    return parsed


def classify_price(price: float, params: BatteryParameters) -> tuple[str, bool]:
    spike_risk = price > params.spike_price_threshold
    if price > params.high_price_threshold:
        return "discharge", spike_risk
    if price < params.low_price_threshold:
        return "charge", spike_risk
    return "idle", spike_risk


def run_dispatch(points: list[dict[str, Any]], params: BatteryParameters) -> list[dict[str, Any]]:
    soc = params.initial_soc_mwh
    rows = []
    for point in points:
        price = float(point["predicted_price"])
        signal, spike_risk = classify_price(price, params)
        soc_start = soc
        charge_mw = 0.0
        discharge_mw = 0.0
        charge_mwh_grid = 0.0
        energy_added_mwh = 0.0
        discharge_mwh_grid = 0.0
        energy_removed_mwh = 0.0
        constrained_reason = ""

        if signal == "charge":
            available_room = max(0.0, params.max_soc_mwh - soc_start)
            max_charge_by_soc = available_room / (params.charge_efficiency * params.interval_hours)
            charge_mw = min(params.max_charge_power_mw, max_charge_by_soc)
            if charge_mw <= 1e-9:
                charge_mw = 0.0
                constrained_reason = "SOC at or above max"
            charge_mwh_grid = charge_mw * params.interval_hours
            energy_added_mwh = charge_mwh_grid * params.charge_efficiency
            soc = soc_start + energy_added_mwh
        elif signal == "discharge":
            available_energy = max(0.0, soc_start - params.min_soc_mwh)
            max_discharge_by_soc = available_energy * params.discharge_efficiency / params.interval_hours
            discharge_mw = min(params.max_discharge_power_mw, max_discharge_by_soc)
            if discharge_mw <= 1e-9:
                discharge_mw = 0.0
                constrained_reason = "SOC at or below min"
            discharge_mwh_grid = discharge_mw * params.interval_hours
            energy_removed_mwh = discharge_mwh_grid / params.discharge_efficiency if params.discharge_efficiency else 0.0
            soc = soc_start - energy_removed_mwh

        soc = min(params.max_soc_mwh, max(params.min_soc_mwh, soc))
        charge_cost = price * charge_mwh_grid
        discharge_revenue = price * discharge_mwh_grid
        cycle_cost = params.cycle_cost_aud_per_mwh * discharge_mwh_grid
        net_revenue = discharge_revenue - charge_cost - cycle_cost

        rows.append(
            {
                **point,
                "rule_signal": signal,
                "spike_risk": spike_risk,
                "soc_start_mwh": round(soc_start, 6),
                "charge_mw": round(charge_mw, 6),
                "discharge_mw": round(discharge_mw, 6),
                "charge_mwh_grid": round(charge_mwh_grid, 6),
                "energy_added_mwh": round(energy_added_mwh, 6),
                "discharge_mwh_grid": round(discharge_mwh_grid, 6),
                "energy_removed_mwh": round(energy_removed_mwh, 6),
                "soc_end_mwh": round(soc, 6),
                "charge_cost_aud": round(charge_cost, 6),
                "discharge_revenue_aud": round(discharge_revenue, 6),
                "cycle_cost_aud": round(cycle_cost, 6),
                "net_revenue_aud": round(net_revenue, 6),
                "constrained_reason": constrained_reason,
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if fieldnames is None:
        fieldnames = list(rows[0].keys()) if rows else []
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_parameters(path: Path, params: BatteryParameters) -> None:
    rows = [
        {"parameter": key, "value": value, "unit": PARAM_UNITS.get(key, "")}
        for key, value in asdict(params).items()
    ]
    write_csv(path, rows, ["parameter", "value", "unit"])


def build_price_rows(points: list[dict[str, Any]], params: BatteryParameters) -> list[dict[str, Any]]:
    rows = []
    for point in points:
        signal, spike_risk = classify_price(float(point["predicted_price"]), params)
        rows.append({**point, "rule_signal": signal, "spike_risk": spike_risk})
    return rows


def build_soc_rows(dispatch_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "timestamp": row["timestamp"],
            "date": row["date"],
            "half_hour_index": row["half_hour_index"],
            "soc_start_mwh": row["soc_start_mwh"],
            "soc_end_mwh": row["soc_end_mwh"],
        }
        for row in dispatch_rows
    ]


def build_summary_rows(dispatch_rows: list[dict[str, Any]], params: BatteryParameters) -> list[dict[str, Any]]:
    total_charge_mwh = sum(float(row["charge_mwh_grid"]) for row in dispatch_rows)
    total_discharge_mwh = sum(float(row["discharge_mwh_grid"]) for row in dispatch_rows)
    total_charge_cost = sum(float(row["charge_cost_aud"]) for row in dispatch_rows)
    total_discharge_revenue = sum(float(row["discharge_revenue_aud"]) for row in dispatch_rows)
    total_cycle_cost = sum(float(row["cycle_cost_aud"]) for row in dispatch_rows)
    total_net_revenue = sum(float(row["net_revenue_aud"]) for row in dispatch_rows)
    charge_intervals = sum(1 for row in dispatch_rows if float(row["charge_mw"]) > 0)
    discharge_intervals = sum(1 for row in dispatch_rows if float(row["discharge_mw"]) > 0)
    spike_intervals = sum(1 for row in dispatch_rows if row["spike_risk"])
    equivalent_cycles = total_discharge_mwh / params.capacity_mwh if params.capacity_mwh else math.nan
    final_soc = float(dispatch_rows[-1]["soc_end_mwh"]) if dispatch_rows else params.initial_soc_mwh
    return [
        {"metric": "total_charge_mwh_grid", "value": round(total_charge_mwh, 6), "unit": "MWh"},
        {"metric": "total_discharge_mwh_grid", "value": round(total_discharge_mwh, 6), "unit": "MWh"},
        {"metric": "total_charge_cost", "value": round(total_charge_cost, 6), "unit": "AUD"},
        {"metric": "total_discharge_revenue", "value": round(total_discharge_revenue, 6), "unit": "AUD"},
        {"metric": "total_cycle_cost", "value": round(total_cycle_cost, 6), "unit": "AUD"},
        {"metric": "total_net_revenue", "value": round(total_net_revenue, 6), "unit": "AUD"},
        {"metric": "charge_intervals", "value": charge_intervals, "unit": "interval"},
        {"metric": "discharge_intervals", "value": discharge_intervals, "unit": "interval"},
        {"metric": "spike_risk_intervals", "value": spike_intervals, "unit": "interval"},
        {"metric": "equivalent_discharge_cycles", "value": round(equivalent_cycles, 6), "unit": "cycle"},
        {"metric": "initial_soc", "value": params.initial_soc_mwh, "unit": "MWh"},
        {"metric": "final_soc", "value": round(final_soc, 6), "unit": "MWh"},
    ]


def validation_report(points: list[dict[str, Any]], rows: list[dict[str, Any]], params: BatteryParameters) -> str:
    errors = []
    warnings = []
    if len(points) != 336:
        warnings.append(f"Expected 336 forecast points, got {len(points)}")
    timestamps = [row["timestamp"] for row in rows]
    if len(timestamps) != len(set(timestamps)):
        errors.append("Duplicate timestamps found")
    for row in rows:
        soc_start = float(row["soc_start_mwh"])
        soc_end = float(row["soc_end_mwh"])
        charge_mw = float(row["charge_mw"])
        discharge_mw = float(row["discharge_mw"])
        if soc_start < params.min_soc_mwh - 1e-6 or soc_end < params.min_soc_mwh - 1e-6:
            errors.append(f"SOC below min at {row['timestamp']}")
        if soc_start > params.max_soc_mwh + 1e-6 or soc_end > params.max_soc_mwh + 1e-6:
            errors.append(f"SOC above max at {row['timestamp']}")
        if charge_mw > params.max_charge_power_mw + 1e-6:
            errors.append(f"Charge power above max at {row['timestamp']}")
        if discharge_mw > params.max_discharge_power_mw + 1e-6:
            errors.append(f"Discharge power above max at {row['timestamp']}")
        if charge_mw > 1e-6 and discharge_mw > 1e-6:
            errors.append(f"Simultaneous charge/discharge at {row['timestamp']}")

    lines = [
        "Battery strategy validation checks",
        f"generated_at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"forecast_points: {len(points)}",
        f"dispatch_rows: {len(rows)}",
        f"soc_min_limit_mwh: {params.min_soc_mwh}",
        f"soc_max_limit_mwh: {params.max_soc_mwh}",
        f"max_charge_power_mw: {params.max_charge_power_mw}",
        f"max_discharge_power_mw: {params.max_discharge_power_mw}",
        "",
        "warnings:",
    ]
    lines.extend(f"- {warning}" for warning in warnings)
    if not warnings:
        lines.append("- none")
    lines.append("")
    lines.append("errors:")
    lines.extend(f"- {error}" for error in errors)
    if not errors:
        lines.append("- none")
    lines.append("")
    lines.append("status: PASS" if not errors else "status: FAIL")
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run rule-based battery arbitrage on a 7-day forecast JSON.")
    parser.add_argument(
        "--forecast-json",
        default=str(DEFAULT_FORECAST_JSON),
        help="Path or URL to forecast JSON. Default: ForecastDashboard/forecast_sample.json",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for CSV outputs. Default: BatteryStrategy/outputs",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    params = BatteryParameters()
    payload = load_forecast(args.forecast_json)
    points = parse_points(payload)
    dispatch_rows = run_dispatch(points, params)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    write_parameters(output_dir / "battery_parameters.csv", params)
    write_csv(output_dir / "price_forecast_used.csv", build_price_rows(points, params))
    write_csv(output_dir / "battery_dispatch_result.csv", dispatch_rows)
    write_csv(output_dir / "soc_curve.csv", build_soc_rows(dispatch_rows))
    write_csv(output_dir / "revenue_summary.csv", build_summary_rows(dispatch_rows, params))
    (output_dir / "validation_checks.txt").write_text(
        validation_report(points, dispatch_rows, params),
        encoding="utf-8",
    )

    print(f"Saved battery strategy outputs to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
