const DATA = window.ECG_DATA;

const metrics = {
  pooled_f1_pct: { label: "Pooled F1", unit: "%", better: "high", digits: 3 },
  f1_drop_from_reference_pp: { label: "F1下降", unit: "pp", better: "low", digits: 3 },
  raw_bitrate_bps: { label: "原始码率", unit: "bit/s", better: "low", digits: 0 },
  median_timing_error_ms: { label: "R峰时间误差", unit: "ms", better: "low", digits: 2 },
  quantization_rmse_uv_mean: { label: "量化RMSE", unit: "uV", better: "low", digits: 2 },
};

const figures = [
  ["系统框图", "../figures/figure_01_system_diagram.png", "虚拟可穿戴ECG采集与R峰检测系统框图。"],
  ["实验流程", "../figures/figure_02_experiment_workflow.png", "数据下载、预处理、重采样、量化、检测和统计分析流程。"],
  ["波形对比", "../figures/figure_03_waveform_comparison.png", "不同采样率和ADC位数下的代表性ECG波形。"],
  ["Clean热力图", "../figures/figure_04_clean_heatmaps.png", "干净条件下30种配置的全因子性能热力图。"],
  ["抗噪曲线", "../figures/figure_05_noise_robustness.png", "标准运动伪影条件下的SNR鲁棒性评估。"],
  ["Pareto权衡", "../figures/figure_06_pareto_tradeoff.png", "检测性能与原始数据率之间的Pareto权衡。"],
  ["严重噪声", "../figures/figure_07_severe_noise_heatmap.png", "低SNR场景下不同配置的失效风险。"],
  ["记录分布", "../figures/figure_08_record_distribution.png", "逐记录性能分布与异常记录情况。"],
];

const state = {
  fs: DATA.recommended.target_fs_hz,
  bits: DATA.recommended.bits,
  metric: "pooled_f1_pct",
  tableFilter: "all",
};

const el = (id) => document.getElementById(id);
const fmt = (value, digits = 2) => Number(value).toFixed(digits);

function configKey(row) {
  return `${Number(row.target_fs_hz)} Hz / ${Number(row.bits)} bit`;
}

function findCandidate(fs, bits) {
  return DATA.candidates.find((row) => Number(row.target_fs_hz) === Number(fs) && Number(row.bits) === Number(bits));
}

function formatMetric(value, metricKey) {
  const meta = metrics[metricKey] || { unit: "", digits: 2 };
  return `${fmt(value, meta.digits)} ${meta.unit}`.trim();
}

function setOptions() {
  const fsValues = [...new Set(DATA.clean.map((row) => Number(row.target_fs_hz)))].sort((a, b) => b - a);
  const bitValues = [...new Set(DATA.clean.map((row) => Number(row.bits)))].sort((a, b) => b - a);
  el("fsSelect").innerHTML = fsValues.map((value) => `<option value="${value}">${value} Hz</option>`).join("");
  el("bitsSelect").innerHTML = bitValues.map((value) => `<option value="${value}">${value} bit</option>`).join("");
  el("fsSelect").value = state.fs;
  el("bitsSelect").value = state.bits;
}

function renderHero() {
  const rec = DATA.recommended;
  el("heroFs").textContent = `${Number(rec.target_fs_hz)} Hz`;
  el("heroBits").textContent = `${Number(rec.bits)} bit`;
  el("metricCleanF1").textContent = `${fmt(rec.pooled_f1_pct, 3)}%`;
  el("metricBitrateDrop").textContent = `${fmt(rec.bitrate_reduction_pct, 1)}%`;
  el("metricBitrate").textContent = `${fmt(rec.raw_bitrate_bps, 0)} bit/s`;
  el("metricNoiseDrop").textContent = `${fmt(rec.worst_noise_f1_drop_pp, 3)} pp`;
}

function renderSelected() {
  const row = findCandidate(state.fs, state.bits);
  if (!row) return;
  el("selectedTitle").textContent = configKey(row);
  el("selectedBadge").textContent = row.meets_all ? "满足约束" : "未满足全部约束";
  el("selectedBadge").className = `badge ${row.meets_all ? "pass" : "fail"}`;

  const cards = [
    ["Pooled F1", `${fmt(row.pooled_f1_pct, 3)}%`],
    ["相对参考F1下降", `${fmt(row.f1_drop_from_reference_pp, 3)} pp`],
    ["原始码率", `${fmt(row.raw_bitrate_bps, 0)} bit/s`],
    ["每日存储", `${fmt(row.storage_mib_per_day, 2)} MiB`],
    ["R峰时间误差中位数", `${fmt(row.median_timing_error_ms, 2)} ms`],
    ["噪声最坏F1下降", `${fmt(row.worst_noise_f1_drop_pp, 3)} pp`],
    ["量化RMSE", `${fmt(row.quantization_rmse_uv_mean, 2)} uV`],
    ["模拟过渡带", `${fmt(row.analog_transition_band_hz, 1)} Hz`],
  ];
  el("selectedDetails").innerHTML = cards
    .map(([label, value]) => `<div class="detail-card"><span>${label}</span><strong>${value}</strong></div>`)
    .join("");
}

function colorFor(value, min, max, better) {
  const span = max - min || 1;
  let t = (value - min) / span;
  if (better === "low") t = 1 - t;
  const hue = 8 + t * 165;
  const light = 88 - t * 34;
  return `hsl(${hue}, 62%, ${light}%)`;
}

function renderHeatmap() {
  const metricKey = state.metric;
  const meta = metrics[metricKey];
  const fsValues = [...new Set(DATA.clean.map((row) => Number(row.target_fs_hz)))].sort((a, b) => b - a);
  const bitValues = [...new Set(DATA.clean.map((row) => Number(row.bits)))].sort((a, b) => b - a);
  const values = DATA.clean.map((row) => Number(row[metricKey]));
  const min = Math.min(...values);
  const max = Math.max(...values);
  el("heatmapUnit").textContent = meta.unit || "value";

  const cells = [`<div class="heat-label">fs \\ bit</div>`];
  bitValues.forEach((bit) => cells.push(`<div class="heat-label">${bit}</div>`));
  fsValues.forEach((fs) => {
    cells.push(`<div class="heat-label">${fs} Hz</div>`);
    bitValues.forEach((bit) => {
      const row = DATA.clean.find((item) => Number(item.target_fs_hz) === fs && Number(item.bits) === bit);
      const value = Number(row[metricKey]);
      const selected = Number(state.fs) === fs && Number(state.bits) === bit ? " is-selected" : "";
      cells.push(
        `<button class="heat-cell${selected}" data-fs="${fs}" data-bits="${bit}" style="background:${colorFor(
          value,
          min,
          max,
          meta.better,
        )}" title="${configKey(row)} · ${meta.label}: ${formatMetric(value, metricKey)}">${formatMetric(value, metricKey)}</button>`,
      );
    });
  });
  el("heatmap").innerHTML = cells.join("");
}

function svgLine(rows, xScale, yScale) {
  return rows.map((row, index) => `${index ? "L" : "M"} ${xScale(Number(row.snr_db))} ${yScale(Number(row.pooled_f1_pct))}`).join(" ");
}

function renderNoiseChart() {
  const selected = DATA.noise
    .filter((row) => Number(row.target_fs_hz) === Number(state.fs) && Number(row.bits) === Number(state.bits))
    .sort((a, b) => Number(a.snr_db) - Number(b.snr_db));
  const reference = DATA.noise
    .filter((row) => Number(row.target_fs_hz) === 360 && Number(row.bits) === 11)
    .sort((a, b) => Number(a.snr_db) - Number(b.snr_db));
  const allRows = [...selected, ...reference];
  const snrs = allRows.map((row) => Number(row.snr_db));
  const f1s = allRows.map((row) => Number(row.pooled_f1_pct));
  const minX = Math.min(...snrs);
  const maxX = Math.max(...snrs);
  const minY = Math.max(0, Math.floor(Math.min(...f1s) / 10) * 10 - 5);
  const maxY = 101;
  const width = 720;
  const height = 300;
  const pad = { l: 48, r: 18, t: 16, b: 42 };
  const xScale = (x) => pad.l + ((x - minX) / (maxX - minX || 1)) * (width - pad.l - pad.r);
  const yScale = (y) => pad.t + (1 - (y - minY) / (maxY - minY || 1)) * (height - pad.t - pad.b);
  const yTicks = [60, 70, 80, 90, 100].filter((tick) => tick >= minY);

  const xLabels = [...new Set(snrs)].sort((a, b) => a - b);
  const selectedPoints = selected
    .map(
      (row) =>
        `<circle class="chart-point" cx="${xScale(Number(row.snr_db))}" cy="${yScale(Number(row.pooled_f1_pct))}" r="4" stroke="#0f766e"><title>${Number(
          row.snr_db,
        )} dB · ${fmt(row.pooled_f1_pct, 2)}%</title></circle>`,
    )
    .join("");
  const referencePoints = reference
    .map(
      (row) =>
        `<circle class="chart-point" cx="${xScale(Number(row.snr_db))}" cy="${yScale(Number(row.pooled_f1_pct))}" r="4" stroke="#c87932"><title>360 Hz / 11 bit · ${Number(
          row.snr_db,
        )} dB · ${fmt(row.pooled_f1_pct, 2)}%</title></circle>`,
    )
    .join("");

  el("noiseChart").innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" aria-hidden="true">
      <rect x="0" y="0" width="${width}" height="${height}" fill="#fff"></rect>
      ${yTicks
        .map(
          (tick) =>
            `<line x1="${pad.l}" x2="${width - pad.r}" y1="${yScale(tick)}" y2="${yScale(tick)}" stroke="#e4ebe8"></line><text class="axis-text" x="8" y="${yScale(tick) + 4}">${tick}%</text>`,
        )
        .join("")}
      ${xLabels
        .map((tick) => `<text class="axis-text" x="${xScale(tick) - 10}" y="${height - 12}">${tick}</text>`)
        .join("")}
      <path class="line-reference" d="${svgLine(reference, xScale, yScale)}"></path>
      <path class="line-main" d="${svgLine(selected, xScale, yScale)}"></path>
      ${referencePoints}
      ${selectedPoints}
      <text class="axis-text" x="${width - 95}" y="24" fill="#0f766e">当前配置</text>
      <text class="axis-text" x="${width - 124}" y="44" fill="#c87932">360 Hz / 11 bit</text>
      <text class="axis-text" x="${width / 2 - 30}" y="${height - 2}">SNR (dB)</text>
    </svg>`;
}

function filteredCandidates() {
  let rows = [...DATA.candidates];
  if (state.tableFilter === "pass") rows = rows.filter((row) => row.meets_all);
  if (state.tableFilter === "practical") rows = rows.filter((row) => row.analog_practical);
  if (state.tableFilter === "low-bitrate") rows = rows.filter((row) => Number(row.raw_bitrate_bps) < 1500);
  return rows.sort((a, b) => Number(b.meets_all) - Number(a.meets_all) || Number(a.raw_bitrate_bps) - Number(b.raw_bitrate_bps));
}

function renderTable() {
  const rows = filteredCandidates();
  el("tableCount").textContent = `${rows.length} rows`;
  el("candidateRows").innerHTML = rows
    .map((row) => {
      const selected = Number(row.target_fs_hz) === Number(state.fs) && Number(row.bits) === Number(state.bits);
      return `<tr class="${selected ? "is-selected" : ""}" data-fs="${Number(row.target_fs_hz)}" data-bits="${Number(row.bits)}">
        <td><strong>${configKey(row)}</strong></td>
        <td>${fmt(row.pooled_f1_pct, 3)}%</td>
        <td>${fmt(row.f1_drop_from_reference_pp, 3)} pp</td>
        <td>${fmt(row.raw_bitrate_bps, 0)} bit/s</td>
        <td>${fmt(row.worst_noise_f1_drop_pp, 3)} pp</td>
        <td class="${row.meets_all ? "pass" : "fail"}">${row.meets_all ? "PASS" : "CHECK"}</td>
      </tr>`;
    })
    .join("");
}

function renderFigures() {
  const tabs = figures
    .map(
      ([label], index) =>
        `<button type="button" class="${index === 3 ? "active" : ""}" data-index="${index}" role="tab">${label}</button>`,
    )
    .join("");
  el("figureTabs").innerHTML = tabs;
}

function updateAll() {
  el("fsSelect").value = state.fs;
  el("bitsSelect").value = state.bits;
  el("metricSelect").value = state.metric;
  el("tableFilter").value = state.tableFilter;
  renderSelected();
  renderHeatmap();
  renderNoiseChart();
  renderTable();
}

function bindEvents() {
  el("fsSelect").addEventListener("change", (event) => {
    state.fs = Number(event.target.value);
    updateAll();
  });
  el("bitsSelect").addEventListener("change", (event) => {
    state.bits = Number(event.target.value);
    updateAll();
  });
  el("metricSelect").addEventListener("change", (event) => {
    state.metric = event.target.value;
    updateAll();
  });
  el("tableFilter").addEventListener("change", (event) => {
    state.tableFilter = event.target.value;
    updateAll();
  });
  el("heatmap").addEventListener("click", (event) => {
    const target = event.target.closest(".heat-cell");
    if (!target) return;
    state.fs = Number(target.dataset.fs);
    state.bits = Number(target.dataset.bits);
    updateAll();
  });
  el("candidateRows").addEventListener("click", (event) => {
    const target = event.target.closest("tr");
    if (!target) return;
    state.fs = Number(target.dataset.fs);
    state.bits = Number(target.dataset.bits);
    updateAll();
  });
  el("figureTabs").addEventListener("click", (event) => {
    const target = event.target.closest("button");
    if (!target) return;
    const index = Number(target.dataset.index);
    const [, src, caption] = figures[index];
    el("figureImage").src = src;
    el("figureCaption").textContent = caption;
    [...el("figureTabs").querySelectorAll("button")].forEach((button) => button.classList.remove("active"));
    target.classList.add("active");
  });
}

setOptions();
renderHero();
renderFigures();
bindEvents();
updateAll();
