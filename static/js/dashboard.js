/**
 * dashboard.js — 中国发展数据可视化平台
 *
 * 数据来源: World Bank Open Data API (免费、无需注册)
 * https://datahelpdesk.worldbank.org/knowledgebase/articles/889392-about-the-indicators-api-documentation
 *
 * 图表库: Apache ECharts 5 (开源)
 */

"use strict";

/* ─────────────────────────────────────────────
   工具函数
───────────────────────────────────────────── */

/**
 * 从 World Bank Indicators API 获取数据
 * @param {string} country  - 国家代码, 如 "CN"
 * @param {string} indicator - 指标代码, 如 "NY.GDP.MKTP.CD"
 * @param {number} perPage   - 返回条数
 * @returns {Promise<Array>}  - 按年份升序排列的 [{year, value}]
 */
async function fetchWB(country, indicator, perPage = 60) {
  const url =
    `https://api.worldbank.org/v2/country/${country}/indicator/${indicator}` +
    `?format=json&per_page=${perPage}&mrv=${perPage}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`World Bank API 请求失败: ${res.status}`);
  const json = await res.json();
  // json[0] 为元数据, json[1] 为数据数组
  const rows = (json[1] || [])
    .filter(d => d.value !== null)
    .map(d => ({ year: Number(d.date), value: d.value }))
    .sort((a, b) => a.year - b.year);
  return rows;
}

/**
 * 批量获取多个国家的单一指标（某一年）
 * 使用 World Bank countries/all 批量接口
 */
async function fetchWBMultiCountry(countries, indicator, year = 2022) {
  const url =
    `https://api.worldbank.org/v2/country/${countries.join(";")}/indicator/${indicator}` +
    `?format=json&per_page=20&date=${year}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error(`World Bank API 请求失败: ${res.status}`);
  const json = await res.json();
  return (json[1] || []).filter(d => d.value !== null);
}

/** 将数字格式化为易读字符串 */
function fmtNum(n, digits = 2) {
  if (n == null) return "—";
  if (Math.abs(n) >= 1e12) return (n / 1e12).toFixed(digits) + " 万亿";
  if (Math.abs(n) >= 1e8) return (n / 1e8).toFixed(digits) + " 亿";
  if (Math.abs(n) >= 1e4) return (n / 1e4).toFixed(digits) + " 万";
  return n.toFixed(digits);
}
function fmtUSD(n) {
  if (n == null) return "—";
  if (Math.abs(n) >= 1e12) return "$" + (n / 1e12).toFixed(2) + "T";
  if (Math.abs(n) >= 1e9) return "$" + (n / 1e9).toFixed(1) + "B";
  return "$" + n.toFixed(0);
}

/** 移除骨架屏 class */
function clearSkeleton(id) {
  document.getElementById(id).classList.remove("skeleton");
}

/* ─────────────────────────────────────────────
   ECharts 全局主题配置
───────────────────────────────────────────── */
const THEME = {
  bg: "transparent",
  textColor: "#8aaad4",
  lineColor: "#1a3060",
  blue: "#1e90ff",
  cyan: "#00d4ff",
  green: "#36d68c",
  orange: "#f5a623",
  red: "#ff5e5e",
  purple: "#9b59b6",
  yellow: "#f0c040",
  gray: "#4a70a8",
};

const BASE_OPTS = {
  backgroundColor: THEME.bg,
  textStyle: {
    color: THEME.textColor,
    fontFamily: "'WQY','PingFang SC','Microsoft YaHei',sans-serif",
  },
  grid: { top: 40, right: 20, bottom: 40, left: 60, containLabel: true },
  tooltip: {
    backgroundColor: "#0d1b3e",
    borderColor: "#1a3060",
    textStyle: {
      color: "#c8d8f8",
      fontFamily: "'WQY','PingFang SC','Microsoft YaHei',sans-serif",
    },
  },
  axisPointer: { lineStyle: { color: "#1e5090" } },
};

function makeLineChart(dom, xData, series, opts = {}) {
  const chart = echarts.init(dom, null, { renderer: "canvas" });
  chart.setOption({
    ...BASE_OPTS,
    xAxis: {
      type: "category",
      data: xData,
      axisLine: { lineStyle: { color: THEME.lineColor } },
      axisLabel: { color: THEME.textColor },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      axisLine: { lineStyle: { color: THEME.lineColor } },
      axisLabel: { color: THEME.textColor },
      splitLine: { lineStyle: { color: "#0f1e3a", type: "dashed" } },
      ...opts.yAxis,
    },
    legend: opts.legend
      ? { textStyle: { color: THEME.textColor }, top: 0 }
      : undefined,
    series,
    tooltip: { ...BASE_OPTS.tooltip, trigger: "axis" },
    dataZoom: opts.zoom
      ? [
          { type: "inside", start: 0, end: 100 },
          {
            type: "slider", bottom: 0, height: 16,
            borderColor: "#1a3060", backgroundColor: "#0a0f1e",
            dataBackground: { lineStyle: { color: THEME.blue }, areaStyle: { color: "#0d2040" } },
            fillerColor: "rgba(30,144,255,0.15)",
            handleStyle: { color: THEME.blue },
            textStyle: { color: THEME.textColor },
          },
        ]
      : undefined,
    ...opts.extra,
  });
  return chart;
}

/* ─────────────────────────────────────────────
   图表 1 — GDP 总量趋势 (折线 + 面积)
───────────────────────────────────────────── */
async function renderGDPChart(data) {
  const years = data.map(d => d.year);
  const vals = data.map(d => d.value / 1e12); // 转换为万亿美元

  clearSkeleton("gdpChart");
  const chart = makeLineChart(
    document.getElementById("gdpChart"),
    years,
    [
      {
        name: "GDP（万亿美元）",
        type: "line",
        data: vals,
        smooth: true,
        symbol: "circle",
        symbolSize: 5,
        lineStyle: { color: THEME.blue, width: 3 },
        itemStyle: { color: THEME.blue },
        areaStyle: {
          color: {
            type: "linear", x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: "rgba(30,144,255,0.45)" },
              { offset: 1, color: "rgba(30,144,255,0.02)" },
            ],
          },
        },
        markLine: {
          silent: true,
          lineStyle: { color: THEME.orange, type: "dashed", width: 1.5 },
          label: { color: THEME.orange, fontSize: 11 },
          data: [
            { type: "max", name: "最大值" },
          ],
        },
        markPoint: {
          data: [
            {
              coord: [1990, vals[0]],
              value: vals[0]?.toFixed(1) + "T",
              itemStyle: { color: THEME.cyan },
              label: { color: "#fff" },
            },
          ],
          symbol: "pin",
          symbolSize: 40,
        },
      },
    ],
    {
      zoom: true,
      yAxis: {
        axisLabel: {
          color: THEME.textColor,
          formatter: v => v.toFixed(1) + "T$",
        },
      },
      extra: {
        tooltip: {
          ...BASE_OPTS.tooltip,
          trigger: "axis",
          formatter: params => {
            const p = params[0];
            return `${p.name}年<br/>GDP：$${p.value.toFixed(2)} 万亿`;
          },
        },
      },
    }
  );
  return chart;
}

/* ─────────────────────────────────────────────
   图表 2 — GDP 增长率 (柱状)
───────────────────────────────────────────── */
async function renderGDPGrowthChart(data) {
  const years = data.map(d => d.year);
  const vals = data.map(d => parseFloat(d.value.toFixed(2)));

  clearSkeleton("gdpGrowthChart");
  const chart = echarts.init(document.getElementById("gdpGrowthChart"), null, { renderer: "canvas" });
  chart.setOption({
    ...BASE_OPTS,
    xAxis: {
      type: "category",
      data: years,
      axisLine: { lineStyle: { color: THEME.lineColor } },
      axisLabel: { color: THEME.textColor, rotate: 35 },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      axisLine: { lineStyle: { color: THEME.lineColor } },
      axisLabel: { color: THEME.textColor, formatter: v => v + "%" },
      splitLine: { lineStyle: { color: "#0f1e3a", type: "dashed" } },
    },
    series: [
      {
        name: "GDP增长率",
        type: "bar",
        data: vals.map(v => ({
          value: v,
          itemStyle: {
            color: v >= 0
              ? new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                  { offset: 0, color: THEME.green },
                  { offset: 1, color: "rgba(54,214,140,0.2)" },
                ])
              : new echarts.graphic.LinearGradient(0, 1, 0, 0, [
                  { offset: 0, color: THEME.red },
                  { offset: 1, color: "rgba(255,94,94,0.2)" },
                ]),
          },
        })),
        barMaxWidth: 24,
        label: {
          show: false,
        },
        markLine: {
          silent: true,
          lineStyle: { color: THEME.gray, type: "dashed" },
          data: [{ yAxis: 0 }],
          label: { show: false },
        },
      },
    ],
    tooltip: {
      ...BASE_OPTS.tooltip,
      trigger: "axis",
      formatter: params => `${params[0].name}年 增长率：${params[0].value}%`,
    },
  });
  return chart;
}

/* ─────────────────────────────────────────────
   图表 3 — 人口 + 城镇化率 (双轴)
───────────────────────────────────────────── */
async function renderPopChart(popData, urbanData) {
  // 对齐年份
  const yearSet = new Set([...popData.map(d => d.year), ...urbanData.map(d => d.year)]);
  const years = [...yearSet].sort();
  const popMap = Object.fromEntries(popData.map(d => [d.year, d.value / 1e8]));
  const urbanMap = Object.fromEntries(urbanData.map(d => [d.year, d.value]));

  clearSkeleton("popChart");
  const chart = echarts.init(document.getElementById("popChart"), null, { renderer: "canvas" });
  chart.setOption({
    ...BASE_OPTS,
    legend: { top: 0, textStyle: { color: THEME.textColor } },
    xAxis: {
      type: "category",
      data: years,
      axisLine: { lineStyle: { color: THEME.lineColor } },
      axisLabel: { color: THEME.textColor, rotate: 30 },
      splitLine: { show: false },
    },
    yAxis: [
      {
        type: "value", name: "人口（亿）",
        nameTextStyle: { color: THEME.textColor, fontSize: 11 },
        axisLine: { lineStyle: { color: THEME.lineColor } },
        axisLabel: { color: THEME.textColor, formatter: v => v.toFixed(1) + "亿" },
        splitLine: { lineStyle: { color: "#0f1e3a", type: "dashed" } },
      },
      {
        type: "value", name: "城镇化率（%）", nameLocation: "end",
        nameTextStyle: { color: THEME.textColor, fontSize: 11 },
        axisLine: { lineStyle: { color: THEME.lineColor } },
        axisLabel: { color: THEME.textColor, formatter: v => v + "%" },
        splitLine: { show: false },
        min: 20, max: 80,
      },
    ],
    series: [
      {
        name: "总人口",
        type: "bar",
        yAxisIndex: 0,
        data: years.map(y => popMap[y] ?? null),
        barMaxWidth: 18,
        itemStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: THEME.cyan },
            { offset: 1, color: "rgba(0,212,255,0.15)" },
          ]),
        },
      },
      {
        name: "城镇化率",
        type: "line",
        yAxisIndex: 1,
        data: years.map(y => urbanMap[y]?.toFixed(1) ?? null),
        smooth: true,
        symbol: "circle", symbolSize: 5,
        lineStyle: { color: THEME.orange, width: 2.5 },
        itemStyle: { color: THEME.orange },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: "rgba(245,166,35,0.2)" },
            { offset: 1, color: "rgba(245,166,35,0)" },
          ]),
        },
      },
    ],
    tooltip: {
      ...BASE_OPTS.tooltip,
      trigger: "axis",
      formatter: params => {
        const yr = params[0]?.name;
        return params.map(p =>
          `${p.marker}${p.seriesName}：${p.value ?? "—"}${p.seriesIndex === 0 ? " 亿" : "%"}`
        ).join("<br/>") + `<br/><span style="color:#4a70a8;font-size:11px">${yr} 年</span>`;
      },
    },
  });
  return chart;
}

/* ─────────────────────────────────────────────
   图表 4 — 主要经济体 GDP 对比 (水平柱状)
───────────────────────────────────────────── */
async function renderCompareChart(rawData) {
  const LABELS = {
    US: "🇺🇸 美国", CN: "🇨🇳 中国", JP: "🇯🇵 日本",
    DE: "🇩🇪 德国", GB: "🇬🇧 英国", IN: "🇮🇳 印度",
    FR: "🇫🇷 法国", IT: "🇮🇹 意大利", CA: "🇨🇦 加拿大", KR: "🇰🇷 韩国",
  };
  const COLORS = {
    US: "#1e90ff", CN: "#ff5e5e", JP: "#f5a623",
    DE: "#36d68c", GB: "#00d4ff", IN: "#f0c040",
    FR: "#9b59b6", IT: "#e67e22", CA: "#3498db", KR: "#2ecc71",
  };

  // 按 GDP 降序排列
  const sorted = rawData
    .filter(d => LABELS[d.countryiso3code] || LABELS[d.country?.id])
    .map(d => ({
      // prefer 2-letter country.id (matches LABELS/COLORS keys)
      code: d.country?.id || d.countryiso3code,
      name: LABELS[d.country?.id] || LABELS[d.countryiso3code] || d.country?.value,
      value: d.value / 1e12,
    }))
    .sort((a, b) => a.value - b.value); // ascending for horizontal bar

  clearSkeleton("compareChart");
  const chart = echarts.init(document.getElementById("compareChart"), null, { renderer: "canvas" });
  chart.setOption({
    ...BASE_OPTS,
    grid: { top: 10, right: 100, bottom: 10, left: 10, containLabel: true },
    xAxis: {
      type: "value",
      axisLine: { lineStyle: { color: THEME.lineColor } },
      axisLabel: { color: THEME.textColor, formatter: v => "$" + v.toFixed(0) + "T" },
      splitLine: { lineStyle: { color: "#0f1e3a", type: "dashed" } },
    },
    yAxis: {
      type: "category",
      data: sorted.map(d => d.name),
      axisLine: { lineStyle: { color: THEME.lineColor } },
      axisLabel: { color: THEME.textColor },
      splitLine: { show: false },
    },
    series: [
      {
        type: "bar",
        data: sorted.map(d => ({
          value: d.value,
          itemStyle: { color: COLORS[d.code] || THEME.blue, borderRadius: [0, 6, 6, 0] },
          label: {
            show: true, position: "right",
            color: "#c8d8f8", fontSize: 12,
            formatter: p => "$" + p.value.toFixed(2) + "T",
          },
        })),
        barMaxWidth: 28,
        label: { show: true, position: "right", color: "#c8d8f8" },
      },
    ],
    tooltip: {
      ...BASE_OPTS.tooltip,
      trigger: "axis",
      formatter: params => `${params[0].name}<br/>GDP：$${params[0].value.toFixed(2)} 万亿美元（2022）`,
    },
  });
  return chart;
}

/* ─────────────────────────────────────────────
   图表 5 — 人均 GDP 趋势 (折线)
───────────────────────────────────────────── */
async function renderGDPPCChart(data) {
  const years = data.map(d => d.year);
  const vals = data.map(d => Math.round(d.value));

  clearSkeleton("gdpPcChart");
  const chart = makeLineChart(
    document.getElementById("gdpPcChart"),
    years,
    [
      {
        name: "人均 GDP（美元）",
        type: "line",
        data: vals,
        smooth: true,
        symbol: "circle", symbolSize: 4,
        lineStyle: { color: THEME.red, width: 2.5 },
        itemStyle: { color: THEME.red },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: "rgba(255,94,94,0.4)" },
            { offset: 1, color: "rgba(255,94,94,0.02)" },
          ]),
        },
      },
    ],
    {
      zoom: true,
      yAxis: {
        axisLabel: { color: THEME.textColor, formatter: v => "$" + v.toLocaleString() },
      },
      extra: {
        tooltip: {
          ...BASE_OPTS.tooltip,
          trigger: "axis",
          formatter: p => `${p[0].name}年<br/>人均 GDP：$${p[0].value.toLocaleString()}`,
        },
      },
    }
  );
  return chart;
}

/* ─────────────────────────────────────────────
   图表 6 — 贸易总额 (出口 + 进口，堆叠面积)
───────────────────────────────────────────── */
async function renderTradeChart(exportData, importData) {
  const yearSet = new Set([...exportData.map(d => d.year), ...importData.map(d => d.year)]);
  const years = [...yearSet].sort();
  const expMap = Object.fromEntries(exportData.map(d => [d.year, +(d.value / 1e9).toFixed(1)]));
  const impMap = Object.fromEntries(importData.map(d => [d.year, +(d.value / 1e9).toFixed(1)]));

  clearSkeleton("tradeChart");
  const chart = echarts.init(document.getElementById("tradeChart"), null, { renderer: "canvas" });
  chart.setOption({
    ...BASE_OPTS,
    legend: { top: 0, textStyle: { color: THEME.textColor } },
    xAxis: {
      type: "category", data: years,
      axisLine: { lineStyle: { color: THEME.lineColor } },
      axisLabel: { color: THEME.textColor, rotate: 30 },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      axisLine: { lineStyle: { color: THEME.lineColor } },
      axisLabel: { color: THEME.textColor, formatter: v => "$" + v + "B" },
      splitLine: { lineStyle: { color: "#0f1e3a", type: "dashed" } },
    },
    series: [
      {
        name: "出口",
        type: "line",
        data: years.map(y => expMap[y] ?? null),
        smooth: true,
        lineStyle: { color: THEME.green, width: 2.5 },
        itemStyle: { color: THEME.green },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: "rgba(54,214,140,0.35)" },
            { offset: 1, color: "rgba(54,214,140,0.03)" },
          ]),
        },
        symbol: "circle", symbolSize: 4,
      },
      {
        name: "进口",
        type: "line",
        data: years.map(y => impMap[y] ?? null),
        smooth: true,
        lineStyle: { color: THEME.purple, width: 2.5 },
        itemStyle: { color: THEME.purple },
        areaStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: "rgba(155,89,182,0.35)" },
            { offset: 1, color: "rgba(155,89,182,0.03)" },
          ]),
        },
        symbol: "circle", symbolSize: 4,
      },
    ],
    tooltip: {
      ...BASE_OPTS.tooltip,
      trigger: "axis",
      formatter: params => {
        return `${params[0]?.name} 年<br/>` +
          params.map(p => `${p.marker}${p.seriesName}：$${p.value ?? "—"}B`).join("<br/>");
      },
    },
  });
  return chart;
}

/* ─────────────────────────────────────────────
   图表 7 — CO₂ 排放 (柱状 + 折线趋势)
───────────────────────────────────────────── */
async function renderCO2Chart(data) {
  const years = data.map(d => d.year);
  // World Bank 单位是千吨，转换为百万吨
  const vals = data.map(d => +(d.value / 1e3).toFixed(0));

  clearSkeleton("co2Chart");
  const chart = echarts.init(document.getElementById("co2Chart"), null, { renderer: "canvas" });
  chart.setOption({
    ...BASE_OPTS,
    xAxis: {
      type: "category", data: years,
      axisLine: { lineStyle: { color: THEME.lineColor } },
      axisLabel: { color: THEME.textColor, rotate: 30 },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value",
      axisLine: { lineStyle: { color: THEME.lineColor } },
      axisLabel: { color: THEME.textColor, formatter: v => v + " Mt" },
      splitLine: { lineStyle: { color: "#0f1e3a", type: "dashed" } },
    },
    series: [
      {
        name: "CO₂排放",
        type: "bar",
        data: vals,
        barMaxWidth: 20,
        itemStyle: {
          color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: "#e74c3c" },
            { offset: 1, color: "rgba(231,76,60,0.15)" },
          ]),
          borderRadius: [4, 4, 0, 0],
        },
        markLine: {
          silent: true,
          lineStyle: { color: THEME.orange, type: "dashed", width: 1.5 },
          data: [{ type: "max", name: "峰值" }],
          label: { color: THEME.orange, fontSize: 11 },
        },
      },
      {
        name: "趋势线",
        type: "line",
        data: vals,
        smooth: true,
        lineStyle: { color: THEME.orange, width: 2, opacity: 0.8 },
        itemStyle: { color: THEME.orange },
        symbol: "none",
        tooltip: { show: false },
      },
    ],
    tooltip: {
      ...BASE_OPTS.tooltip,
      trigger: "axis",
      formatter: params => `${params[0].name}年<br/>CO₂排放：${params[0].value.toLocaleString()} 百万吨`,
    },
    dataZoom: [
      { type: "inside", start: 0, end: 100 },
      {
        type: "slider", bottom: 0, height: 16,
        borderColor: "#1a3060", backgroundColor: "#0a0f1e",
        fillerColor: "rgba(231,76,60,0.15)",
        handleStyle: { color: "#e74c3c" },
        textStyle: { color: THEME.textColor },
      },
    ],
  });
  return chart;
}

/* ─────────────────────────────────────────────
   KPI 更新
───────────────────────────────────────────── */
function updateKPI(id, value, growth, fmt = v => v) {
  const el = document.getElementById(id);
  if (el) el.textContent = fmt(value);
  if (growth != null) {
    const gEl = document.getElementById(id + "-growth");
    if (gEl) {
      const sign = growth >= 0 ? "▲ +" : "▼ ";
      gEl.textContent = sign + growth.toFixed(2) + "%";
      gEl.className = "kpi-sub " + (growth >= 0 ? "kpi-up" : "kpi-down");
    }
  }
}

function calcGrowth(data, lastYear = 2022) {
  const sorted = [...data].sort((a, b) => a.year - b.year);
  const curr = sorted.find(d => d.year === lastYear);
  const prev = sorted.find(d => d.year === lastYear - 1);
  if (!curr || !prev) return null;
  return ((curr.value - prev.value) / prev.value) * 100;
}

/* ─────────────────────────────────────────────
   API 封装（带离线备用数据）
───────────────────────────────────────────── */

/**
 * 尝试从 World Bank API 获取数据，失败时使用离线备用数据
 */
async function fetchWBWithFallback(country, indicator, perPage, fallback) {
  try {
    return await fetchWB(country, indicator, perPage);
  } catch {
    console.warn(`API 不可用，使用离线数据 [${indicator}]`);
    return fallback || [];
  }
}

async function fetchWBMultiCountryWithFallback(countries, indicator, year, fallback) {
  try {
    return await fetchWBMultiCountry(countries, indicator, year);
  } catch {
    console.warn(`API 不可用，使用离线对比数据 [${indicator}]`);
    return fallback || [];
  }
}

/* ─────────────────────────────────────────────
   主入口
───────────────────────────────────────────── */
async function main() {
  const badge = document.getElementById("loading-badge");
  const ts = document.getElementById("data-timestamp");
  badge.classList.add("visible");

  const FB = window.WB_FALLBACK || {};

  try {
    // ---- 并行拉取所有数据（API 优先，离线数据保底）----
    const [
      gdpData,
      gdpGrowthData,
      popData,
      urbanData,
      gdpPcData,
      exportData,
      importData,
      co2Data,
      compareRaw,
    ] = await Promise.all([
      fetchWBWithFallback("CN", "NY.GDP.MKTP.CD",    60, FB.gdp),
      fetchWBWithFallback("CN", "NY.GDP.MKTP.KD.ZG", 60, FB.gdpGrowth),
      fetchWBWithFallback("CN", "SP.POP.TOTL",        60, FB.pop),
      fetchWBWithFallback("CN", "SP.URB.TOTL.IN.ZS",  60, FB.urban),
      fetchWBWithFallback("CN", "NY.GDP.PCAP.CD",     60, FB.gdpPc),
      fetchWBWithFallback("CN", "NE.EXP.GNFS.CD",     60, FB.exports),
      fetchWBWithFallback("CN", "NE.IMP.GNFS.CD",     60, FB.imports),
      fetchWBWithFallback("CN", "EN.ATM.CO2E.KT",     60, FB.co2),
      fetchWBMultiCountryWithFallback(
        ["US", "CN", "JP", "DE", "GB", "IN", "FR", "IT", "CA", "KR"],
        "NY.GDP.MKTP.CD", 2022, FB.compareGDP),
    ]);

    // ---- KPI ----
    const latestGDP    = gdpData.filter(d => d.year <= 2022).at(-1);
    const latestPop    = popData.filter(d => d.year <= 2022).at(-1);
    const latestGdpPc  = gdpPcData.filter(d => d.year <= 2022).at(-1);
    const latestUrban  = urbanData.filter(d => d.year <= 2022).at(-1);
    const latestGrowth = gdpGrowthData.filter(d => d.year <= 2022).at(-1);

    updateKPI("kpi-gdp",      latestGDP?.value,    calcGrowth(gdpData, latestGDP?.year),
      v => "$" + (v / 1e12).toFixed(2) + " 万亿");
    updateKPI("kpi-pop",      latestPop?.value,    calcGrowth(popData, latestPop?.year),
      v => (v / 1e8).toFixed(2) + " 亿");
    updateKPI("kpi-gdp-rate", latestGrowth?.value, null,
      v => v.toFixed(2) + "%");
    updateKPI("kpi-gdp-pc",   latestGdpPc?.value,  calcGrowth(gdpPcData, latestGdpPc?.year),
      v => "$" + Math.round(v).toLocaleString());
    updateKPI("kpi-urban",    latestUrban?.value,  calcGrowth(urbanData, latestUrban?.year),
      v => v.toFixed(1) + "%");

    // ---- 渲染图表 ----
    await Promise.all([
      renderGDPChart(gdpData.filter(d => d.year >= 1990)),
      renderGDPGrowthChart(gdpGrowthData.filter(d => d.year >= 1985)),
      renderPopChart(popData.filter(d => d.year >= 1980), urbanData.filter(d => d.year >= 1980)),
      renderCompareChart(compareRaw),
      renderGDPPCChart(gdpPcData.filter(d => d.year >= 1990)),
      renderTradeChart(exportData.filter(d => d.year >= 1990), importData.filter(d => d.year >= 1990)),
      renderCO2Chart(co2Data.filter(d => d.year >= 1990)),
    ]);

    const isLive = gdpData !== FB.gdp;
    ts.textContent = new Date().toLocaleString("zh-CN", { hour12: false }) +
      (isLive ? "" : "（离线数据）");
    badge.classList.remove("visible");
    badge.textContent = isLive ? "✓ 实时数据已加载" : "✓ 离线数据已加载";
    badge.style.background = "rgba(54,214,140,0.15)";
    badge.style.borderColor = "#36d68c";
    badge.style.color = "#36d68c";
    badge.classList.add("visible");
  } catch (err) {
    console.error("数据渲染失败:", err);
    badge.textContent = "⚠ 渲染失败：" + err.message;
    badge.style.borderColor = "#ff5e5e";
    badge.style.color = "#ff5e5e";
    badge.classList.add("visible");
  }

  // ---- 响应式 resize ----
  window.addEventListener("resize", () => {
    ["gdpChart","gdpGrowthChart","popChart","compareChart",
     "gdpPcChart","tradeChart","co2Chart"].forEach(id => {
      echarts.getInstanceByDom(document.getElementById(id))?.resize();
    });
  });
}

document.addEventListener("DOMContentLoaded", main);
