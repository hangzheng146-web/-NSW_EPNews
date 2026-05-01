const fmt = new Intl.NumberFormat("en-AU", { maximumFractionDigits: 1 });
const qtyFmt = new Intl.NumberFormat("en-AU", { maximumFractionDigits: 3 });
let forecastPayload = null;
let batteryPayload = null;

async function loadForecast() {
  const dateParam = document.getElementById("forecastDate")?.value;
  const apiUrl = dateParam ? `/api/forecast?forecast_start=${encodeURIComponent(dateParam)}` : "/api/forecast";
  try {
    const response = await fetch(apiUrl, { cache: "no-store" });
    if (!response.ok) throw new Error(await response.text());
    forecastPayload = await response.json();
  } catch (error) {
    console.warn("API forecast failed, falling back to static sample", error);
    const response = await fetch("forecast_sample.json", { cache: "no-store" });
    forecastPayload = await response.json();
    forecastPayload.metadata.warnings = [
      "后端实时预测 API 不可用，当前显示静态样例 forecast_sample.json。",
    ];
  }
  render(forecastPayload);
}

async function loadBatteryStrategy(forecastStart = null, runForDate = false) {
  try {
    document.getElementById("batteryStatus").textContent = runForDate ? "Running" : "Loading";
    const url =
      runForDate && forecastStart
        ? `/api/battery-strategy/run?forecast_start=${encodeURIComponent(forecastStart)}`
        : "/api/battery-strategy";
    const response = await fetch(url, { cache: "no-store" });
    if (!response.ok) throw new Error(await response.text());
    batteryPayload = await response.json();
    renderBatteryStrategy(batteryPayload);
  } catch (error) {
    document.getElementById("batteryStatus").textContent = "Load failed";
    document.getElementById("batteryValidationText").textContent = String(error);
    console.error(error);
  }
}

async function runBatteryForCurrentDate() {
  const forecastStart = forecastPayload?.metadata?.forecast_start || document.getElementById("forecastDate")?.value;
  if (!forecastStart) return;
  await loadBatteryStrategy(forecastStart, true);
}

function avg(values) {
  return values.reduce((a, b) => a + b, 0) / values.length;
}

function groupByDate(points) {
  return points.reduce((map, point) => {
    if (!map.has(point.date)) map.set(point.date, []);
    map.get(point.date).push(point);
    return map;
  }, new Map());
}

function opportunityLevel(spread) {
  if (spread >= 150) return "strong";
  if (spread >= 80) return "medium";
  return "weak";
}

function dailySummary(points, thresholds) {
  return [...groupByDate(points).entries()].map(([date, dayPoints]) => {
    const prices = dayPoints.map((p) => p.predicted_price);
    const max = Math.max(...prices);
    const min = Math.min(...prices);
    const spread = max - min;
    return {
      date,
      avg_price: avg(prices),
      max_price: max,
      min_price: min,
      peak_valley_spread: spread,
      high_price_count: prices.filter((v) => v >= thresholds.high_price_threshold).length,
      low_price_count: prices.filter((v) => v <= thresholds.low_price_threshold).length,
      spike_count: prices.filter((v) => v >= thresholds.spike_threshold).length,
      opportunity_level: opportunityLevel(spread),
    };
  });
}

function weeklySummary(points, daily, thresholds) {
  const prices = points.map((p) => p.predicted_price);
  const max = Math.max(...prices);
  const min = Math.min(...prices);
  const best = [...daily].sort((a, b) => b.peak_valley_spread - a.peak_valley_spread)[0];
  return {
    avg_price: avg(prices),
    max_price: max,
    min_price: min,
    max_spread: max - min,
    spike_count: prices.filter((v) => v >= thresholds.spike_threshold).length,
    best_opportunity_day: best?.date ?? "-",
  };
}

function mergeWindows(points, predicate, valueKey, reason) {
  const windows = [];
  let current = null;
  for (const point of points) {
    if (predicate(point)) {
      if (!current) {
        current = { start: point.timestamp, end: point.timestamp, values: [point.predicted_price] };
      } else {
        current.end = point.timestamp;
        current.values.push(point.predicted_price);
      }
    } else if (current) {
      windows.push(closeWindow(current, valueKey, reason));
      current = null;
    }
  }
  if (current) windows.push(closeWindow(current, valueKey, reason));
  return windows;
}

function addThirtyMinutes(timestamp) {
  const date = new Date(timestamp.replace(" ", "T"));
  date.setMinutes(date.getMinutes() + 30);
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

function closeWindow(win, valueKey, reason) {
  const closed = { start: win.start, end: addThirtyMinutes(win.end), reason };
  if (valueKey === "max_price") closed.max_price = Math.max(...win.values);
  else closed.avg_price = avg(win.values);
  return closed;
}

function tradingWindows(points, thresholds) {
  return {
    charge_windows: mergeWindows(
      points,
      (p) => p.predicted_price <= thresholds.low_price_threshold,
      "avg_price",
      "连续低价窗口"
    ),
    discharge_windows: mergeWindows(
      points,
      (p) => p.predicted_price >= thresholds.high_price_threshold,
      "avg_price",
      "高价放电窗口"
    ),
    spike_risk_windows: mergeWindows(
      points,
      (p) => p.predicted_price >= thresholds.spike_threshold,
      "max_price",
      "预测价格超过尖峰阈值"
    ),
  };
}

function money(value) {
  return `${fmt.format(value)} AUD/MWh`;
}

function aud(value) {
  return `${qtyFmt.format(Number(value || 0))} AUD`;
}

function mwh(value) {
  return `${qtyFmt.format(Number(value || 0))} MWh`;
}

function metricValue(rows, metric) {
  const row = rows.find((item) => item.metric === metric);
  return row ? Number(row.value) : 0;
}

function actionLabel(action) {
  if (action === "charge") return "充电";
  if (action === "discharge") return "放电";
  return "不动";
}

function parameterNote(parameter) {
  const notes = {
    capacity_mwh: "电池总容量，表示最多可以存多少电。",
    max_charge_power_mw: "最大充电功率，表示每个时段最多能以多大功率充电。",
    max_discharge_power_mw: "最大放电功率，表示每个时段最多能以多大功率放电。",
    initial_soc_mwh: "初始 SOC，表示策略开始时电池已有电量。",
    min_soc_mwh: "最低 SOC 下限，电池电量不能低于这个值。",
    max_soc_mwh: "最高 SOC 上限，电池电量不能高于这个值。",
    charge_efficiency: "充电效率，表示买入电量进入电池后的保留比例。",
    discharge_efficiency: "放电效率，表示电池放电到电网时的效率损耗。",
    cycle_cost_aud_per_mwh: "循环成本，用来近似电池充放电造成的寿命和运维成本。",
    interval_hours: "每个调度时间步长度，0.5 表示半小时。",
    low_price_threshold: "低价阈值，预测价格低于该值时尝试充电。",
    high_price_threshold: "高价阈值，预测价格高于该值时尝试放电。",
    spike_price_threshold: "尖峰风险阈值，预测价格高于该值时标记为尖峰风险。",
  };
  return notes[parameter] || "策略参数。";
}

function render(payload) {
  const { metadata, thresholds, point_forecast: points } = payload;
  const daily = dailySummary(points, thresholds);
  const weekly = weeklySummary(points, daily, thresholds);
  const windows = tradingWindows(points, thresholds);

  document.getElementById("modelStatus").textContent = metadata.model_name;
  document.getElementById("regionInput").value = metadata.region;
  document.getElementById("forecastDate").value = metadata.forecast_start;
  document.getElementById("daysInput").value = metadata.forecast_days;
  document.getElementById("frequencyInput").value = metadata.frequency;
  document.getElementById("modelInput").value = metadata.model_name;
  document.getElementById("generatedInput").value = metadata.generated_at;
  renderWarnings(metadata.warnings || []);

  document.getElementById("avgPrice").textContent = money(weekly.avg_price);
  document.getElementById("maxPrice").textContent = money(weekly.max_price);
  document.getElementById("minPrice").textContent = money(weekly.min_price);
  document.getElementById("maxSpread").textContent = money(weekly.max_spread);
  document.getElementById("spikeCount").textContent = weekly.spike_count;
  document.getElementById("bestDay").textContent = weekly.best_opportunity_day;

  renderDailyTable(daily);
  renderWindowTable("chargeBody", windows.charge_windows, "avg_price");
  renderWindowTable("dischargeBody", windows.discharge_windows, "avg_price");
  renderWindowTable("riskBody", windows.spike_risk_windows, "max_price");
  drawChart(points, thresholds);
  markBatteryPending(metadata.forecast_start);
}

function renderBatteryStrategy(payload) {
  const summary = payload.revenue_summary || [];
  const counts = payload.counts || {};
  const tables = payload.tables || {};
  const metadata = payload.metadata || {};
  const pageDate = forecastPayload?.metadata?.forecast_start || document.getElementById("forecastDate")?.value || "-";
  const strategyDate = metadata.forecast_start || "-";
  const netRevenue = metricValue(summary, "total_net_revenue");
  const dischargeIntervals = counts.actual_discharge_intervals ?? 0;

  document.getElementById("batteryStatus").textContent = payload.validation_status || "-";
  document.getElementById("batteryRunDate").textContent = strategyDate;
  document.getElementById("batteryRunId").textContent = metadata.run_id || "-";
  document.getElementById("batteryTrace").textContent =
    `可回溯目录：${metadata.source_directory}；页面数据来自 battery_parameters.csv、price_forecast_used.csv、battery_dispatch_result.csv、soc_curve.csv、revenue_summary.csv、validation_checks.txt。`;
  document.getElementById("batteryMismatchWarning").innerHTML =
    strategyDate !== "-" && pageDate !== strategyDate
      ? "<p>当前储能策略结果与页面预测日期不一致，请点击运行当前日期储能策略模拟。</p>"
      : "";
  document.getElementById("batteryPageDate").textContent = pageDate;
  document.getElementById("batterySourceDate").textContent = strategyDate;
  document.getElementById("batterySourceRunId").textContent = metadata.run_id || "-";
  document.getElementById("batteryOutputDir").textContent = metadata.source_directory || "-";
  document.getElementById("batteryGeneratedAt").textContent = metadata.generated_at || "-";
  document.getElementById("batterySourceStatus").textContent = payload.validation_status || "-";

  document.getElementById("batteryCharged").textContent = mwh(metricValue(summary, "total_charge_mwh_grid"));
  document.getElementById("batteryDischarged").textContent = mwh(metricValue(summary, "total_discharge_mwh_grid"));
  document.getElementById("batteryNetRevenue").textContent = `${aud(netRevenue)}${netRevenue < 0 ? "（亏损）" : ""}`;
  document.getElementById("batteryOverviewChargeIntervals").textContent = counts.actual_charge_intervals ?? "-";
  document.getElementById("batteryOverviewDischargeIntervals").textContent = dischargeIntervals;
  document.getElementById("batteryIdleIntervals").textContent = counts.actual_idle_intervals ?? "-";
  document.getElementById("batteryFinalSoc").textContent = mwh(metricValue(summary, "final_soc"));
  document.getElementById("batteryOverviewStatus").textContent = payload.validation_status || "-";
  document.getElementById("batteryDischargeNote").textContent =
    dischargeIntervals === 0 ? "本次预测期内未触发高价放电阈值，因此没有放电收入。" : "";

  document.getElementById("batteryForecastRows").textContent = counts.forecast_points ?? "-";
  document.getElementById("batteryDispatchRows").textContent = counts.dispatch_rows ?? "-";
  document.getElementById("batteryChargeIntervals").textContent = counts.actual_charge_intervals ?? "-";
  document.getElementById("batteryDischargeIntervals").textContent = dischargeIntervals;
  document.getElementById("batterySpikeIntervals").textContent = counts.spike_risk_intervals ?? "-";
  document.getElementById("batteryValidationStatus").textContent = payload.validation_status || "-";
  document.getElementById("batteryInterpretation").textContent = payload.interpretation?.message || "-";
  document.getElementById("batteryValidationText").textContent =
    `${payload.validation_status === "PASS" ? "校验通过" : "校验未通过，请检查输出文件"}\n\n${payload.validation_text || "-"}`;

  renderBatteryParams(payload.parameters || []);
  renderBatteryDispatch(tables.battery_dispatch_result || []);
  drawSocChart(tables.soc_curve || []);
}

function markBatteryPending(forecastStart) {
  document.getElementById("batteryStatus").textContent = "待运行";
  document.getElementById("batteryRunDate").textContent = forecastStart || "-";
  document.getElementById("batteryRunId").textContent = "-";
  document.getElementById("batteryPageDate").textContent = forecastStart || "-";
  document.getElementById("batterySourceDate").textContent = "-";
  document.getElementById("batterySourceRunId").textContent = "-";
  document.getElementById("batteryOutputDir").textContent = "-";
  document.getElementById("batteryGeneratedAt").textContent = "-";
  document.getElementById("batterySourceStatus").textContent = "待运行";
  document.getElementById("batteryMismatchWarning").innerHTML = "";
  document.getElementById("batteryTrace").textContent =
    "预测结果已刷新。点击“运行储能策略模拟”后，后端会生成 BatteryStrategy/runs/当前日期/ 下的可回溯输出文件。";
  document.getElementById("batteryInterpretation").textContent = "当前日期的储能策略尚未运行。";
  document.getElementById("batteryValidationText").textContent = "待运行。";
}

function renderBatteryParams(rows) {
  document.getElementById("batteryParamsBody").innerHTML = rows
    .map(
      (r) => `<tr>
        <td>${r.parameter}</td>
        <td>${parameterNote(r.parameter)}</td>
        <td>${r.value}</td>
        <td>${r.unit}</td>
      </tr>`
    )
    .join("");
}

function renderBatteryDispatch(rows) {
  document.getElementById("batteryDispatchBody").innerHTML = rows
    .map(
      (r) => `<tr>
        <td>${r.timestamp}</td>
        <td>${fmt.format(Number(r.predicted_price))}</td>
        <td><span class="badge ${r.rule_signal}">${actionLabel(r.rule_signal)}</span></td>
        <td>${qtyFmt.format(Number(r.charge_mwh_grid))}</td>
        <td>${qtyFmt.format(Number(r.discharge_mwh_grid))}</td>
        <td>${qtyFmt.format(Number(r.soc_start_mwh))}</td>
        <td>${qtyFmt.format(Number(r.soc_end_mwh))}</td>
        <td>${qtyFmt.format(Number(r.net_revenue_aud))}</td>
        <td>${r.constrained_reason || ""}</td>
      </tr>`
    )
    .join("");
}

function renderWarnings(warnings) {
  const container = document.getElementById("dataWarnings");
  container.innerHTML = warnings.map((w) => `<p>${w}</p>`).join("");
}

function renderDailyTable(rows) {
  document.getElementById("dailySummaryBody").innerHTML = rows
    .map(
      (r) => `<tr>
        <td>${r.date}</td>
        <td>${fmt.format(r.avg_price)}</td>
        <td>${fmt.format(r.max_price)}</td>
        <td>${fmt.format(r.min_price)}</td>
        <td>${fmt.format(r.peak_valley_spread)}</td>
        <td>${r.high_price_count}</td>
        <td>${r.low_price_count}</td>
        <td>${r.spike_count}</td>
        <td><span class="badge ${r.opportunity_level}">${r.opportunity_level}</span></td>
      </tr>`
    )
    .join("");
}

function renderWindowTable(id, rows, valueKey) {
  const body = document.getElementById(id);
  if (!rows.length) {
    body.innerHTML = `<tr><td colspan="4">无匹配窗口</td></tr>`;
    return;
  }
  body.innerHTML = rows
    .map(
      (r) => `<tr>
        <td>${r.start}</td>
        <td>${r.end}</td>
        <td>${fmt.format(r[valueKey])}</td>
        <td>${r.reason}</td>
      </tr>`
    )
    .join("");
}

function drawChart(points, thresholds) {
  const canvas = document.getElementById("priceChart");
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const cssWidth = canvas.clientWidth;
  const cssHeight = canvas.clientHeight;
  canvas.width = Math.floor(cssWidth * dpr);
  canvas.height = Math.floor(cssHeight * dpr);
  ctx.scale(dpr, dpr);

  const width = cssWidth;
  const height = cssHeight;
  const pad = { left: 58, right: 20, top: 20, bottom: 44 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const prices = points.map((p) => p.predicted_price);
  const minY = Math.min(0, Math.min(...prices, thresholds.low_price_threshold) - 20);
  const maxY = Math.max(...prices, thresholds.spike_threshold) + 30;

  const x = (i) => pad.left + (i / (points.length - 1)) * plotW;
  const y = (v) => pad.top + (1 - (v - minY) / (maxY - minY)) * plotH;

  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, width, height);

  ctx.strokeStyle = "#e5ebf0";
  ctx.lineWidth = 1;
  ctx.fillStyle = "#64727f";
  ctx.font = "12px system-ui";
  for (let i = 0; i <= 5; i++) {
    const value = minY + ((maxY - minY) * i) / 5;
    const yy = y(value);
    ctx.beginPath();
    ctx.moveTo(pad.left, yy);
    ctx.lineTo(width - pad.right, yy);
    ctx.stroke();
    ctx.fillText(fmt.format(value), 10, yy + 4);
  }

  drawThreshold(ctx, y(thresholds.low_price_threshold), "#047857", width, pad, "低价");
  drawThreshold(ctx, y(thresholds.high_price_threshold), "#b45309", width, pad, "高价");
  drawThreshold(ctx, y(thresholds.spike_threshold), "#b91c1c", width, pad, "尖峰");

  ctx.strokeStyle = "#1d4ed8";
  ctx.lineWidth = 2;
  ctx.beginPath();
  prices.forEach((price, i) => {
    if (i === 0) ctx.moveTo(x(i), y(price));
    else ctx.lineTo(x(i), y(price));
  });
  ctx.stroke();

  const grouped = [...groupByDate(points).keys()];
  ctx.fillStyle = "#64727f";
  grouped.forEach((date, day) => {
    const xx = x(day * 48);
    ctx.strokeStyle = "#eef2f5";
    ctx.beginPath();
    ctx.moveTo(xx, pad.top);
    ctx.lineTo(xx, height - pad.bottom);
    ctx.stroke();
    ctx.fillText(date.slice(5), xx + 4, height - 18);
  });

  ctx.fillStyle = "#1f2933";
  ctx.fillText("AUD/MWh", pad.left, 14);
}

function drawThreshold(ctx, yy, color, width, pad, label) {
  ctx.strokeStyle = color;
  ctx.setLineDash([6, 5]);
  ctx.beginPath();
  ctx.moveTo(pad.left, yy);
  ctx.lineTo(width - pad.right, yy);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.fillStyle = color;
  ctx.fillText(label, width - pad.right - 42, yy - 6);
}

window.addEventListener("resize", () => {
  if (forecastPayload) drawChart(forecastPayload.point_forecast, forecastPayload.thresholds);
  if (batteryPayload) drawSocChart(batteryPayload.tables?.soc_curve || []);
});

document.getElementById("forecastDate").addEventListener("change", () => {
  document.getElementById("modelStatus").textContent = "Refreshing";
  document.getElementById("batteryStatus").textContent = "Waiting";
  loadForecast();
});

document.getElementById("runBatteryButton").addEventListener("click", () => {
  runBatteryForCurrentDate();
});

loadForecast().catch((error) => {
  document.getElementById("modelStatus").textContent = "Load failed";
  console.error(error);
});

function drawSocChart(rows) {
  const canvas = document.getElementById("socChart");
  if (!canvas || !rows.length) return;
  const ctx = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const cssWidth = canvas.clientWidth;
  const cssHeight = canvas.clientHeight;
  canvas.width = Math.floor(cssWidth * dpr);
  canvas.height = Math.floor(cssHeight * dpr);
  ctx.scale(dpr, dpr);

  const width = cssWidth;
  const height = cssHeight;
  const pad = { left: 58, right: 20, top: 18, bottom: 36 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const values = rows.map((r) => Number(r.soc_end_mwh));
  const minY = 0;
  const maxY = 100;
  const x = (i) => pad.left + (i / Math.max(1, rows.length - 1)) * plotW;
  const y = (v) => pad.top + (1 - (v - minY) / (maxY - minY)) * plotH;

  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, width, height);
  ctx.strokeStyle = "#e5ebf0";
  ctx.fillStyle = "#64727f";
  ctx.font = "12px system-ui";
  for (let i = 0; i <= 5; i++) {
    const value = minY + ((maxY - minY) * i) / 5;
    const yy = y(value);
    ctx.beginPath();
    ctx.moveTo(pad.left, yy);
    ctx.lineTo(width - pad.right, yy);
    ctx.stroke();
    ctx.fillText(fmt.format(value), 12, yy + 4);
  }

  drawThreshold(ctx, y(10), "#b91c1c", width, pad, "SOC min");
  drawThreshold(ctx, y(90), "#047857", width, pad, "SOC max");
  ctx.strokeStyle = "#0f766e";
  ctx.lineWidth = 2;
  ctx.beginPath();
  values.forEach((value, index) => {
    if (index === 0) ctx.moveTo(x(index), y(value));
    else ctx.lineTo(x(index), y(value));
  });
  ctx.stroke();
  ctx.fillStyle = "#1f2933";
  ctx.fillText("SOC MWh", pad.left, 13);
}
