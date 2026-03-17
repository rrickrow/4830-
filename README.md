# 中国发展数据可视化平台

> 基于 World Bank 免费开放数据，使用 Apache ECharts 5 构建的中国宏观经济数据可视化仪表盘。

## 项目书（Project Specification）

### 一、项目背景

随着大数据时代的到来，数据可视化成为理解复杂经济数据的重要工具。本项目旨在构建一个面向中国宏观经济发展的交互式数据可视化平台，通过直观的图表展示中国过去数十年的经济发展历程。

### 二、项目目标

1. **真实数据**：直接调用 [World Bank Open Data API](https://data.worldbank.org/)（完全免费，无需注册），确保数据权威、可靠。
2. **美观图表**：使用 [Apache ECharts 5](https://echarts.apache.org/)（百度开源图表库）绘制高质量、交互式图表。
3. **多维展示**：覆盖 GDP 总量、增长率、人均 GDP、人口与城镇化、贸易、碳排放等核心指标。
4. **国际对比**：将中国与全球主要经济体（美日德英印等）进行横向对比。

### 三、数据来源

| 指标 | World Bank 代码 | 说明 |
|------|----------------|------|
| GDP 总量 | `NY.GDP.MKTP.CD` | 现价美元 |
| GDP 增长率 | `NY.GDP.MKTP.KD.ZG` | 年度 % |
| 总人口 | `SP.POP.TOTL` | 人口总数 |
| 城镇化率 | `SP.URB.TOTL.IN.ZS` | 城镇人口占比 % |
| 人均 GDP | `NY.GDP.PCAP.CD` | 现价美元 |
| 出口总额 | `NE.EXP.GNFS.CD` | 商品与服务出口，现价美元 |
| 进口总额 | `NE.IMP.GNFS.CD` | 商品与服务进口，现价美元 |
| CO₂ 排放 | `EN.ATM.CO2E.KT` | 千吨二氧化碳 |

**数据协议**：[Creative Commons Attribution 4.0](https://datacatalog.worldbank.org/public-licenses#cc-by)（CC BY 4.0），可免费使用。

### 四、可视化模块

| 图表 | 类型 | 说明 |
|------|------|------|
| GDP 总量趋势 | 折线 + 面积 | 1990—2022 年，带缩放交互 |
| GDP 年增长率 | 柱状（正负双色） | 正增长绿色，负增长红色 |
| 人口与城镇化率 | 双轴（柱状 + 折线） | 总人口 + 城镇化率联动 |
| 主要经济体对比 | 水平条形 | 10 大经济体 GDP 对比 |
| 人均 GDP 趋势 | 折线 + 面积 | 展示居民生活水平提升 |
| 进出口贸易额 | 双线堆叠面积 | 出口（绿）vs 进口（紫） |
| CO₂ 排放趋势 | 柱状 + 趋势线 | 环境指标，标注历史峰值 |

### 五、技术栈

- **前端**：原生 HTML5 / CSS3 / JavaScript（ES2020）
- **图表库**：[Apache ECharts 5.4](https://echarts.apache.org/)（开源，CDN 引入）
- **数据 API**：[World Bank Indicators API v2](https://datahelpdesk.worldbank.org/knowledgebase/articles/889392)
- **无后端依赖**：纯静态页面，可直接在浏览器中打开

### 六、运行方法

```bash
# 方法一：直接打开（需联网以加载 CDN 和 API 数据）
open index.html

# 方法二：本地 HTTP 服务器（推荐，避免 CORS 问题）
python3 -m http.server 8080
# 然后访问 http://localhost:8080
```

### 七、目录结构

```
4830-/
├── index.html              # 主页面
├── static/
│   └── js/
│       └── dashboard.js    # 图表逻辑 + API 调用
└── README.md               # 项目文档
```

### 八、截图预览

> 运行后，仪表盘顶部显示 KPI 指标卡，下方展示 7 个交互式图表，支持鼠标悬停提示、区间缩放等交互功能。

---

**数据来源**：[World Bank Open Data](https://data.worldbank.org/) ·
**图表库**：[Apache ECharts](https://echarts.apache.org/) ·
**协议**：数据 CC BY 4.0，代码 MIT
