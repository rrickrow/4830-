/**
 * dashboard.js — 松辽流域河道变迁与植被响应遥感分析平台
 *
 * 数据来源：
 *   河道宽度 / 水体面积：Landsat TM/ETM+/OLI (30 m) 遥感影像分类
 *   NDVI：MODIS MOD13Q1 时间序列产品（250 m, 16-day composite）
 *   降水：CHIRPS v2.0 逐年面均降水
 *   离线回退：window.SONGLIAO（fallback-data.js）
 *
 * 图表库：Apache ECharts 5（本地打包，开源 Apache-2.0 协议）
 */

"use strict";

/* ─────────────────────────────────────────────
   常量与颜色主题
───────────────────────────────────────────── */
const THEME = {
  bg:        "transparent",
  text:      "#8aaad4",
  grid:      "#1a3060",
  blue:      "#1e90ff",
  cyan:      "#00d4ff",
  green:     "#36d68c",
  orange:    "#f5a623",
  red:       "#ff5e5e",
  purple:    "#9b59b6",
  yellow:    "#f0c040",
  teal:      "#1abc9c",
  gray:      "#4a70a8",
  fontFamily: "'WQY','PingFang SC','Microsoft YaHei',sans-serif",
};

const BASE_OPTS = {
  backgroundColor: THEME.bg,
  textStyle: { color: THEME.text, fontFamily: THEME.fontFamily },
  grid: { top: 40, right: 20, bottom: 40, left: 60, containLabel: true },
  tooltip: {
    backgroundColor: "#0d1b3e",
    borderColor: "#1a3060",
    textStyle: { color: "#c8d8f8", fontFamily: THEME.fontFamily },
  },
  axisPointer: { lineStyle: { color: "#1e5090" } },
};

/** 移除骨架屏 */
function clearSkeleton(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove("skeleton");
}

/** 通用 ECharts 初始化 */
function initChart(id, opts) {
  clearSkeleton(id);
  const el = document.getElementById(id);
  if (!el) return null;
  const chart = echarts.init(el, null, { renderer: "canvas" });
  chart.setOption(Object.assign({}, BASE_OPTS, opts));
  window.addEventListener("resize", () => chart.resize());
  return chart;
}

/** 获取 years / values 数组 */
function split(arr) {
  return {
    years:  arr.map(d => d.year),
    values: arr.map(d => d.value),
  };
}

/* ─────────────────────────────────────────────
   KPI 更新工具
───────────────────────────────────────────── */
function setKpi(id, text, sub, subClass) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
  const subEl = document.getElementById(id + "-sub");
  if (subEl) {
    subEl.textContent = sub;
    subEl.className = "kpi-sub " + (subClass || "");
  }
}

function pctChange(arr, field = "value") {
  if (!arr || arr.length < 2) return null;
  const last  = arr[arr.length - 1][field];
  const prev  = arr[arr.length - 2][field];
  if (!prev) return null;
  return ((last - prev) / Math.abs(prev)) * 100;
}

function fmtPct(v, decimals = 1) {
  if (v == null) return "—";
  const sign = v >= 0 ? "▲ +" : "▼ ";
  return sign + Math.abs(v).toFixed(decimals) + "%";
}

/* ─────────────────────────────────────────────
   图表 1：松花江 & 辽河主河道宽度趋势（双线）
───────────────────────────────────────────── */
function renderChannelWidthChart(songhua, liao) {
  const { years } = split(songhua);
  initChart("channelWidthChart", {
    legend: {
      data: ["松花江（哈尔滨断面）", "辽河（铁岭断面）"],
      textStyle: { color: THEME.text, fontFamily: THEME.fontFamily },
      top: 4,
    },
    tooltip: {
      trigger: "axis",
      formatter(params) {
        const yr = params[0].axisValue;
        const note = (yr === 1998 || yr === 2013) ? `（${yr} 年洪水）` : "";
        return `${yr} 年${note}<br>` +
          params.map(p => `${p.marker}${p.seriesName}：<b>${p.value} m</b>`).join("<br>");
      },
      backgroundColor: "#0d1b3e", borderColor: "#1a3060",
      textStyle: { color: "#c8d8f8", fontFamily: THEME.fontFamily },
    },
    xAxis: {
      type: "category", data: years,
      axisLine: { lineStyle: { color: THEME.grid } },
      axisTick: { lineStyle: { color: THEME.grid } },
      axisLabel: {
        color: THEME.text, fontFamily: THEME.fontFamily,
        interval: 4, rotate: 30,
      },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value", name: "宽度 (m)",
      nameTextStyle: { color: THEME.text, fontFamily: THEME.fontFamily },
      axisLine: { lineStyle: { color: THEME.grid } },
      splitLine: { lineStyle: { color: THEME.grid, type: "dashed" } },
      axisLabel: { color: THEME.text, fontFamily: THEME.fontFamily },
    },
    series: [
      {
        name: "松花江（哈尔滨断面）",
        type: "line", smooth: true,
        data: songhua.map(d => d.value),
        lineStyle: { color: THEME.blue, width: 2.5 },
        itemStyle: { color: THEME.blue },
        areaStyle: { color: { type: "linear", x:0,y:0,x2:0,y2:1,
          colorStops: [
            {offset:0, color:"rgba(30,144,255,0.25)"},
            {offset:1, color:"rgba(30,144,255,0.02)"},
          ]}},
        markPoint: {
          data: [
            { type: "max", name: "最大值", label: { fontFamily: THEME.fontFamily } },
          ],
          label: { color: "#fff", fontFamily: THEME.fontFamily },
          itemStyle: { color: THEME.orange },
        },
        symbol: "circle", symbolSize: 4,
      },
      {
        name: "辽河（铁岭断面）",
        type: "line", smooth: true,
        data: liao.map(d => d.value),
        lineStyle: { color: THEME.cyan, width: 2.5 },
        itemStyle: { color: THEME.cyan },
        areaStyle: { color: { type: "linear", x:0,y:0,x2:0,y2:1,
          colorStops: [
            {offset:0, color:"rgba(0,212,255,0.2)"},
            {offset:1, color:"rgba(0,212,255,0.02)"},
          ]}},
        symbol: "circle", symbolSize: 4,
      },
    ],
    grid: { top: 50, right: 20, bottom: 50, left: 60, containLabel: true },
  });
}

/* ─────────────────────────────────────────────
   图表 2：地表水体面积趋势
───────────────────────────────────────────── */
function renderWaterAreaChart(data) {
  const { years, values } = split(data);
  initChart("waterAreaChart", {
    tooltip: {
      trigger: "axis",
      formatter: p => `${p[0].axisValue} 年<br>${p[0].marker}水体面积：<b>${p[0].value.toLocaleString()} km²</b>`,
      backgroundColor: "#0d1b3e", borderColor: "#1a3060",
      textStyle: { color: "#c8d8f8", fontFamily: THEME.fontFamily },
    },
    xAxis: {
      type: "category", data: years,
      axisLine: { lineStyle: { color: THEME.grid } },
      axisLabel: { color: THEME.text, fontFamily: THEME.fontFamily, interval: 4, rotate: 30 },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value", name: "面积 (km²)",
      min: v => Math.floor(v.min * 0.92 / 100) * 100,
      nameTextStyle: { color: THEME.text, fontFamily: THEME.fontFamily },
      axisLine: { lineStyle: { color: THEME.grid } },
      splitLine: { lineStyle: { color: THEME.grid, type: "dashed" } },
      axisLabel: { color: THEME.text, fontFamily: THEME.fontFamily },
    },
    series: [{
      type: "bar",
      data: values,
      itemStyle: {
        color: p => {
          const yr = years[p.dataIndex];
          if (yr === 1998 || yr === 2013) return THEME.orange;
          return { type: "linear", x:0,y:0,x2:0,y2:1,
            colorStops: [
              {offset:0, color:"rgba(0,212,255,0.9)"},
              {offset:1, color:"rgba(0,100,200,0.5)"},
            ]};
        },
        borderRadius: [3, 3, 0, 0],
      },
      markLine: {
        data: [{ type: "average", name: "均值" }],
        label: { color: THEME.text, fontFamily: THEME.fontFamily, formatter: "均值: {c}" },
        lineStyle: { color: THEME.yellow, type: "dashed" },
        symbol: ["none","none"],
      },
    }],
    grid: { top: 30, right: 20, bottom: 50, left: 60, containLabel: true },
  });
}

/* ─────────────────────────────────────────────
   图表 3：河岸缓冲带 NDVI 趋势（双线）
───────────────────────────────────────────── */
function renderNdviChart(songhua, liao) {
  const { years } = split(songhua);
  initChart("ndviChart", {
    legend: {
      data: ["松花江河岸带 NDVI", "辽河河岸带 NDVI"],
      textStyle: { color: THEME.text, fontFamily: THEME.fontFamily }, top: 4,
    },
    tooltip: {
      trigger: "axis",
      formatter(params) {
        return `${params[0].axisValue} 年<br>` +
          params.map(p => `${p.marker}${p.seriesName}：<b>${p.value.toFixed(3)}</b>`).join("<br>");
      },
      backgroundColor: "#0d1b3e", borderColor: "#1a3060",
      textStyle: { color: "#c8d8f8", fontFamily: THEME.fontFamily },
    },
    xAxis: {
      type: "category", data: years,
      axisLine: { lineStyle: { color: THEME.grid } },
      axisLabel: { color: THEME.text, fontFamily: THEME.fontFamily, interval: 4, rotate: 30 },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value", name: "NDVI",
      min: 0.3, max: 0.65,
      nameTextStyle: { color: THEME.text, fontFamily: THEME.fontFamily },
      axisLine: { lineStyle: { color: THEME.grid } },
      splitLine: { lineStyle: { color: THEME.grid, type: "dashed" } },
      axisLabel: { color: THEME.text, fontFamily: THEME.fontFamily, formatter: v => v.toFixed(2) },
    },
    series: [
      {
        name: "松花江河岸带 NDVI",
        type: "line", smooth: true,
        data: songhua.map(d => d.value),
        lineStyle: { color: THEME.green, width: 2.5 },
        itemStyle: { color: THEME.green },
        areaStyle: { color: { type: "linear", x:0,y:0,x2:0,y2:1,
          colorStops: [
            {offset:0, color:"rgba(54,214,140,0.25)"},
            {offset:1, color:"rgba(54,214,140,0.02)"},
          ]}},
        symbol: "circle", symbolSize: 4,
      },
      {
        name: "辽河河岸带 NDVI",
        type: "line", smooth: true,
        data: liao.map(d => d.value),
        lineStyle: { color: THEME.yellow, width: 2.5 },
        itemStyle: { color: THEME.yellow },
        areaStyle: { color: { type: "linear", x:0,y:0,x2:0,y2:1,
          colorStops: [
            {offset:0, color:"rgba(240,192,64,0.2)"},
            {offset:1, color:"rgba(240,192,64,0.02)"},
          ]}},
        symbol: "circle", symbolSize: 4,
      },
    ],
    grid: { top: 50, right: 20, bottom: 50, left: 60, containLabel: true },
  });
}

/* ─────────────────────────────────────────────
   图表 4：松花江河道累计迁移距离
───────────────────────────────────────────── */
function renderMigrationChart(data) {
  const { years, values } = split(data);
  initChart("migrationChart", {
    tooltip: {
      trigger: "axis",
      formatter: p => `${p[0].axisValue} 年<br>${p[0].marker}累计迁移：<b>${p[0].value} m</b>`,
      backgroundColor: "#0d1b3e", borderColor: "#1a3060",
      textStyle: { color: "#c8d8f8", fontFamily: THEME.fontFamily },
    },
    xAxis: {
      type: "category", data: years,
      axisLine: { lineStyle: { color: THEME.grid } },
      axisLabel: { color: THEME.text, fontFamily: THEME.fontFamily, interval: 4, rotate: 30 },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value", name: "迁移距离 (m)",
      nameTextStyle: { color: THEME.text, fontFamily: THEME.fontFamily },
      axisLine: { lineStyle: { color: THEME.grid } },
      splitLine: { lineStyle: { color: THEME.grid, type: "dashed" } },
      axisLabel: { color: THEME.text, fontFamily: THEME.fontFamily },
    },
    series: [{
      type: "line", smooth: false,
      data: values,
      step: false,
      lineStyle: { color: THEME.orange, width: 2.5 },
      itemStyle: { color: THEME.orange },
      areaStyle: { color: { type: "linear", x:0,y:0,x2:0,y2:1,
        colorStops: [
          {offset:0, color:"rgba(245,166,35,0.3)"},
          {offset:1, color:"rgba(245,166,35,0.02)"},
        ]}},
      symbol: "circle", symbolSize: 4,
      markPoint: {
        data: (() => {
          // Derive flood-year annotations from the actual data array
          const floodYears = [1998, 2013];
          return floodYears.map(yr => {
            const point = data.find(d => d.year === yr);
            return point ? {
              coord: [yr, point.value],
              name: `${yr} 洪水`,
              label: { formatter: `${yr}\n洪水`, fontFamily: THEME.fontFamily, color: "#fff" },
              itemStyle: { color: THEME.red },
            } : null;
          }).filter(Boolean);
        })(),
        symbolSize: 36,
      },
    }],
    grid: { top: 30, right: 20, bottom: 50, left: 60, containLabel: true },
  });
}

/* ─────────────────────────────────────────────
   图表 5：年降水量趋势（柱 + 折线）
───────────────────────────────────────────── */
function renderPrecipChart(data) {
  const { years, values } = split(data);
  // 5-year moving average
  const ma5 = values.map((_, i, arr) => {
    const slice = arr.slice(Math.max(0, i - 2), i + 3);
    return +(slice.reduce((s, v) => s + v, 0) / slice.length).toFixed(1);
  });
  initChart("precipChart", {
    legend: {
      data: ["年降水量", "5 年滑动平均"],
      textStyle: { color: THEME.text, fontFamily: THEME.fontFamily }, top: 4,
    },
    tooltip: {
      trigger: "axis",
      formatter(params) {
        return `${params[0].axisValue} 年<br>` +
          params.map(p => `${p.marker}${p.seriesName}：<b>${p.value} mm</b>`).join("<br>");
      },
      backgroundColor: "#0d1b3e", borderColor: "#1a3060",
      textStyle: { color: "#c8d8f8", fontFamily: THEME.fontFamily },
    },
    xAxis: {
      type: "category", data: years,
      axisLine: { lineStyle: { color: THEME.grid } },
      axisLabel: { color: THEME.text, fontFamily: THEME.fontFamily, interval: 4, rotate: 30 },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value", name: "降水 (mm)",
      nameTextStyle: { color: THEME.text, fontFamily: THEME.fontFamily },
      axisLine: { lineStyle: { color: THEME.grid } },
      splitLine: { lineStyle: { color: THEME.grid, type: "dashed" } },
      axisLabel: { color: THEME.text, fontFamily: THEME.fontFamily },
    },
    series: [
      {
        name: "年降水量",
        type: "bar",
        data: values,
        itemStyle: {
          color: p => {
            const yr = years[p.dataIndex];
            if (yr === 1998 || yr === 2013) return THEME.red;
            return { type: "linear", x:0,y:0,x2:0,y2:1,
              colorStops: [
                {offset:0, color:"rgba(26,188,156,0.85)"},
                {offset:1, color:"rgba(26,100,120,0.4)"},
              ]};
          },
          borderRadius: [3,3,0,0],
        },
      },
      {
        name: "5 年滑动平均",
        type: "line", smooth: true,
        data: ma5,
        lineStyle: { color: THEME.yellow, width: 2, type: "dashed" },
        itemStyle: { color: THEME.yellow },
        symbol: "none",
      },
    ],
    grid: { top: 50, right: 20, bottom: 50, left: 60, containLabel: true },
  });
}

/* ─────────────────────────────────────────────
   图表 6：河道宽度 vs NDVI 散点图（相关分析）
───────────────────────────────────────────── */
function renderScatterChart(widthData, ndviData) {
  // align by year
  const widthMap = Object.fromEntries(widthData.map(d => [d.year, d.value]));
  const scatterData = ndviData
    .filter(d => widthMap[d.year] != null)
    .map(d => [widthMap[d.year], d.value, d.year]);

  initChart("scatterChart", {
    tooltip: {
      trigger: "item",
      formatter: p => `${p.data[2]} 年<br>河道宽度：<b>${p.data[0]} m</b><br>NDVI：<b>${p.data[1].toFixed(3)}</b>`,
      backgroundColor: "#0d1b3e", borderColor: "#1a3060",
      textStyle: { color: "#c8d8f8", fontFamily: THEME.fontFamily },
    },
    xAxis: {
      type: "value", name: "松花江河道宽度 (m)",
      nameTextStyle: { color: THEME.text, fontFamily: THEME.fontFamily },
      axisLine: { lineStyle: { color: THEME.grid } },
      splitLine: { lineStyle: { color: THEME.grid, type: "dashed" } },
      axisLabel: { color: THEME.text, fontFamily: THEME.fontFamily },
    },
    yAxis: {
      type: "value", name: "河岸带 NDVI",
      nameTextStyle: { color: THEME.text, fontFamily: THEME.fontFamily },
      axisLine: { lineStyle: { color: THEME.grid } },
      splitLine: { lineStyle: { color: THEME.grid, type: "dashed" } },
      axisLabel: { color: THEME.text, fontFamily: THEME.fontFamily, formatter: v => v.toFixed(2) },
    },
    series: [{
      type: "scatter",
      data: scatterData,
      symbolSize: p => (p[2] === 1998 || p[2] === 2013) ? 14 : 8,
      itemStyle: {
        color: p => (p.data[2] === 1998 || p.data[2] === 2013) ? THEME.orange : THEME.blue,
        opacity: 0.85,
      },
      label: {
        show: false,
      },
    }],
    grid: { top: 30, right: 20, bottom: 50, left: 60, containLabel: true },
  });
}

/* ─────────────────────────────────────────────
   图表 7：土地利用变化（分组柱状图）
───────────────────────────────────────────── */
function renderLandUseChart(lu) {
  const colors = [THEME.orange, THEME.green, THEME.teal,
                  THEME.cyan, THEME.blue, THEME.red, THEME.gray];
  initChart("landUseChart", {
    legend: {
      data: ["1990 年", "2005 年", "2022 年"],
      textStyle: { color: THEME.text, fontFamily: THEME.fontFamily }, top: 4,
    },
    tooltip: {
      trigger: "axis", axisPointer: { type: "shadow" },
      formatter(params) {
        return `${params[0].name}<br>` +
          params.map(p => `${p.marker}${p.seriesName}：<b>${p.value.toLocaleString()} km²</b>`).join("<br>");
      },
      backgroundColor: "#0d1b3e", borderColor: "#1a3060",
      textStyle: { color: "#c8d8f8", fontFamily: THEME.fontFamily },
    },
    xAxis: {
      type: "category", data: lu.categories,
      axisLine: { lineStyle: { color: THEME.grid } },
      axisLabel: { color: THEME.text, fontFamily: THEME.fontFamily },
      splitLine: { show: false },
    },
    yAxis: {
      type: "value", name: "面积 (km²)",
      nameTextStyle: { color: THEME.text, fontFamily: THEME.fontFamily },
      axisLine: { lineStyle: { color: THEME.grid } },
      splitLine: { lineStyle: { color: THEME.grid, type: "dashed" } },
      axisLabel: { color: THEME.text, fontFamily: THEME.fontFamily },
    },
    series: [
      { name: "1990 年", type: "bar", data: lu.data1990,
        itemStyle: { color: p => colors[p.dataIndex], opacity: 0.6, borderRadius: [2,2,0,0] } },
      { name: "2005 年", type: "bar", data: lu.data2005,
        itemStyle: { color: p => colors[p.dataIndex], opacity: 0.8, borderRadius: [2,2,0,0] } },
      { name: "2022 年", type: "bar", data: lu.data2022,
        itemStyle: { color: p => colors[p.dataIndex], opacity: 1.0, borderRadius: [2,2,0,0] } },
    ],
    grid: { top: 50, right: 20, bottom: 40, left: 60, containLabel: true },
  });
}

/* ─────────────────────────────────────────────
   KPI 卡片填充
───────────────────────────────────────────── */
function fillKpis(d) {
  // 松花江河道宽度变化
  const sw = d.songhuaWidth;
  const swLast  = sw[sw.length - 1].value;
  const swFirst = sw[0].value;
  const swDiff  = swLast - swFirst;
  const swChg   = (swDiff / swFirst * 100).toFixed(1);
  const swWord  = swDiff < 0 ? "萎缩" : "增宽";
  setKpi("kpi-songhua-width", swLast + " m",
    `较 1990 年 ${swDiff < 0 ? "▼ " : "▲ +"}${swChg}%（${swWord} ${Math.abs(swDiff)} m）`,
    swDiff < 0 ? "kpi-down" : "kpi-up");

  // 辽河河道宽度变化
  const lw = d.liaoWidth;
  const lwLast  = lw[lw.length - 1].value;
  const lwFirst = lw[0].value;
  const lwDiff  = lwLast - lwFirst;
  const lwChg   = (lwDiff / lwFirst * 100).toFixed(1);
  const lwWord  = lwDiff < 0 ? "萎缩" : "增宽";
  setKpi("kpi-liao-width", lwLast + " m",
    `较 1990 年 ${lwDiff < 0 ? "▼ " : "▲ +"}${lwChg}%（${lwWord} ${Math.abs(lwDiff)} m）`,
    lwDiff < 0 ? "kpi-down" : "kpi-up");

  // 松花江河岸 NDVI
  const sn = d.songhuaNdvi;
  const snLast  = sn[sn.length - 1].value;
  const snFirst = sn[0].value;
  const snDiff  = snLast - snFirst;
  const snChg   = (snDiff / snFirst * 100).toFixed(1);
  const snWord  = snDiff >= 0 ? "植被改善" : "植被退化";
  setKpi("kpi-ndvi", snLast.toFixed(3),
    `较 1990 年 ${snDiff >= 0 ? "▲ +" : "▼ "}${snChg}%（${snWord}）`,
    snDiff >= 0 ? "kpi-up" : "kpi-down");

  // 水体面积
  const wa = d.waterArea;
  const waLast  = wa[wa.length - 1].value;
  const waFirst = wa[0].value;
  const waDiff  = waLast - waFirst;
  const waChg   = (waDiff / waFirst * 100).toFixed(1);
  setKpi("kpi-water-area", waLast.toLocaleString() + " km²",
    `较 1990 年 ${waDiff < 0 ? "▼ " : "▲ +"}${waChg}%`,
    waDiff < 0 ? "kpi-down" : "kpi-up");

  // 河道迁移距离
  const cm = d.channelMigration;
  const cmLast = cm[cm.length - 1].value;
  setKpi("kpi-migration", cmLast + " m",
    "1990–2022 年累计迁移距离", "kpi-up");
}

/* ─────────────────────────────────────────────
   主函数：加载离线数据并渲染所有图表
───────────────────────────────────────────── */
function initDashboard() {
  const badge = document.getElementById("loading-badge");
  const ts    = document.getElementById("data-timestamp");

  // 始终使用本地遥感分析数据（无远程 API）
  const d = window.SONGLIAO;

  if (badge) { badge.textContent = "✓ 遥感离线数据"; badge.classList.remove("visible"); }
  if (ts) ts.textContent = new Date().toLocaleString("zh-CN") + "（遥感分析数据）";

  fillKpis(d);

  renderChannelWidthChart(d.songhuaWidth, d.liaoWidth);
  renderWaterAreaChart(d.waterArea);
  renderNdviChart(d.songhuaNdvi, d.liaoNdvi);
  renderMigrationChart(d.channelMigration);
  renderPrecipChart(d.precipitation);
  renderScatterChart(d.songhuaWidth, d.songhuaNdvi);
  renderLandUseChart(d.landUseChange);
}

document.addEventListener("DOMContentLoaded", initDashboard);
