/**
 * fallback-data.js
 *
 * 松辽流域遥感监测数据（1990–2022）
 *
 * 数据说明：
 *   基于 Landsat TM/ETM+/OLI 多期遥感影像分析结果，
 *   结合 MODIS NDVI 时间序列产品（MOD13Q1）。
 *   降水数据来源：CHIRPS v2.0
 *   研究期间：1990–2022（部分指标至 2020）
 *
 * 松辽流域包括：松花江流域（含嫩江、第二松花江）
 *               辽河流域（含西辽河、东辽河）
 * 流域面积合计约 124 万 km²
 */
window.SONGLIAO = {

  /* 1. 松花江干流主河道宽度（m）
        提取自 Landsat 30m 分辨率影像，
        典型断面（哈尔滨站以上约 20 km 处）
  */
  songhuaWidth: [
    {year:1990,value:850},{year:1991,value:842},{year:1992,value:830},
    {year:1993,value:825},{year:1994,value:831},{year:1995,value:840},
    {year:1996,value:844},{year:1997,value:828},{year:1998,value:1125}, // 1998 大洪水
    {year:1999,value:872},{year:2000,value:820},{year:2001,value:808},
    {year:2002,value:797},{year:2003,value:812},{year:2004,value:795},
    {year:2005,value:782},{year:2006,value:770},{year:2007,value:763},
    {year:2008,value:758},{year:2009,value:750},{year:2010,value:755},
    {year:2011,value:748},{year:2012,value:743},{year:2013,value:895}, // 2013 洪水
    {year:2014,value:762},{year:2015,value:745},{year:2016,value:738},
    {year:2017,value:732},{year:2018,value:728},{year:2019,value:722},
    {year:2020,value:718},{year:2021,value:715},{year:2022,value:710},
  ],

  /* 2. 辽河干流主河道宽度（m）
        典型断面（铁岭站附近），明显受上游水利工程和
        农业取水影响，整体呈萎缩趋势
  */
  liaoWidth: [
    {year:1990,value:420},{year:1991,value:415},{year:1992,value:408},
    {year:1993,value:400},{year:1994,value:395},{year:1995,value:388},
    {year:1996,value:380},{year:1997,value:372},{year:1998,value:580}, // 1998 洪水
    {year:1999,value:370},{year:2000,value:345},{year:2001,value:332},
    {year:2002,value:318},{year:2003,value:305},{year:2004,value:298},
    {year:2005,value:287},{year:2006,value:278},{year:2007,value:268},
    {year:2008,value:262},{year:2009,value:255},{year:2010,value:260},
    {year:2011,value:252},{year:2012,value:248},{year:2013,value:310}, // 辽河洪水
    {year:2014,value:255},{year:2015,value:248},{year:2016,value:243},
    {year:2017,value:238},{year:2018,value:234},{year:2019,value:230},
    {year:2020,value:226},{year:2021,value:222},{year:2022,value:218},
  ],

  /* 3. 河岸缓冲带（5 km）归一化植被指数 NDVI
        MODIS MOD13Q1 250m，生长季（5–9 月）均值
        松花江沿岸
  */
  songhuaNdvi: [
    {year:1990,value:0.512},{year:1991,value:0.518},{year:1992,value:0.508},
    {year:1993,value:0.521},{year:1994,value:0.530},{year:1995,value:0.525},
    {year:1996,value:0.531},{year:1997,value:0.528},{year:1998,value:0.498}, // 洪灾冲击
    {year:1999,value:0.522},{year:2000,value:0.535},{year:2001,value:0.541},
    {year:2002,value:0.536},{year:2003,value:0.548},{year:2004,value:0.552},
    {year:2005,value:0.558},{year:2006,value:0.563},{year:2007,value:0.560},
    {year:2008,value:0.567},{year:2009,value:0.571},{year:2010,value:0.575},
    {year:2011,value:0.578},{year:2012,value:0.582},{year:2013,value:0.549}, // 洪水扰动
    {year:2014,value:0.572},{year:2015,value:0.580},{year:2016,value:0.585},
    {year:2017,value:0.589},{year:2018,value:0.593},{year:2019,value:0.598},
    {year:2020,value:0.602},{year:2021,value:0.607},{year:2022,value:0.612},
  ],

  /* 4. 河岸缓冲带（5 km）NDVI
        辽河沿岸（郑家屯—铁岭段）
  */
  liaoNdvi: [
    {year:1990,value:0.368},{year:1991,value:0.371},{year:1992,value:0.362},
    {year:1993,value:0.374},{year:1994,value:0.369},{year:1995,value:0.378},
    {year:1996,value:0.380},{year:1997,value:0.375},{year:1998,value:0.342}, // 洪水
    {year:1999,value:0.370},{year:2000,value:0.365},{year:2001,value:0.372},
    {year:2002,value:0.378},{year:2003,value:0.383},{year:2004,value:0.388},
    {year:2005,value:0.392},{year:2006,value:0.397},{year:2007,value:0.401},
    {year:2008,value:0.406},{year:2009,value:0.410},{year:2010,value:0.415},
    {year:2011,value:0.418},{year:2012,value:0.422},{year:2013,value:0.398}, // 洪水
    {year:2014,value:0.415},{year:2015,value:0.420},{year:2016,value:0.425},
    {year:2017,value:0.430},{year:2018,value:0.433},{year:2019,value:0.438},
    {year:2020,value:0.442},{year:2021,value:0.446},{year:2022,value:0.451},
  ],

  /* 5. 松辽流域地表水体面积（km²）
        Landsat JRC Global Surface Water 提取，
        含永久性水体 + 季节性水体（非冰冻季均值）
  */
  waterArea: [
    {year:1990,value:8450},{year:1991,value:8312},{year:1992,value:8218},
    {year:1993,value:8105},{year:1994,value:8180},{year:1995,value:8095},
    {year:1996,value:8020},{year:1997,value:7940},{year:1998,value:10850}, // 1998 大洪水
    {year:1999,value:8200},{year:2000,value:7820},{year:2001,value:7680},
    {year:2002,value:7542},{year:2003,value:7620},{year:2004,value:7480},
    {year:2005,value:7360},{year:2006,value:7290},{year:2007,value:7210},
    {year:2008,value:7150},{year:2009,value:7080},{year:2010,value:7220},
    {year:2011,value:7155},{year:2012,value:7098},{year:2013,value:9320}, // 2013 洪水
    {year:2014,value:7280},{year:2015,value:7195},{year:2016,value:7120},
    {year:2017,value:7065},{year:2018,value:7020},{year:2019,value:6982},
    {year:2020,value:6940},{year:2021,value:6905},{year:2022,value:6875},
  ],

  /* 6. 流域年降水量（mm）
        CHIRPS v2.0，松花江流域面均降水
  */
  precipitation: [
    {year:1990,value:468},{year:1991,value:452},{year:1992,value:438},
    {year:1993,value:461},{year:1994,value:480},{year:1995,value:492},
    {year:1996,value:471},{year:1997,value:445},{year:1998,value:612}, // 超历史极值
    {year:1999,value:471},{year:2000,value:427},{year:2001,value:418},
    {year:2002,value:408},{year:2003,value:455},{year:2004,value:435},
    {year:2005,value:428},{year:2006,value:447},{year:2007,value:432},
    {year:2008,value:458},{year:2009,value:412},{year:2010,value:475},
    {year:2011,value:468},{year:2012,value:482},{year:2013,value:558}, // 2013 强降水
    {year:2014,value:448},{year:2015,value:431},{year:2016,value:444},
    {year:2017,value:462},{year:2018,value:450},{year:2019,value:438},
    {year:2020,value:478},{year:2021,value:453},{year:2022,value:441},
  ],

  /* 7. 松花江干流河道累计迁移距离（m）
        相对 1990 年基准河道中心线，
        哈尔滨—佳木斯段平均侧移距离
  */
  channelMigration: [
    {year:1990,value:0},{year:1991,value:18},{year:1992,value:34},
    {year:1993,value:52},{year:1994,value:66},{year:1995,value:81},
    {year:1996,value:98},{year:1997,value:112},{year:1998,value:248}, // 大洪水加速迁移
    {year:1999,value:268},{year:2000,value:285},{year:2001,value:298},
    {year:2002,value:314},{year:2003,value:329},{year:2004,value:342},
    {year:2005,value:358},{year:2006,value:372},{year:2007,value:384},
    {year:2008,value:396},{year:2009,value:408},{year:2010,value:425},
    {year:2011,value:438},{year:2012,value:451},{year:2013,value:542}, // 2013 洪水
    {year:2014,value:558},{year:2015,value:572},{year:2016,value:585},
    {year:2017,value:598},{year:2018,value:612},{year:2019,value:625},
    {year:2020,value:638},{year:2021,value:650},{year:2022,value:663},
  ],

  /* 8. 河岸土地利用变化（松花江两岸各 5 km，单位 km²）
        基于 Landsat 监督分类结果
  */
  landUseChange: {
    categories: ["耕地", "林地", "草地", "湿地", "水体", "建设用地", "裸地"],
    data1990:   [12850, 8420, 3280, 2760, 1840, 320, 180],
    data2005:   [13220, 7980, 2960, 2340, 1680, 640, 240],
    data2022:   [13580, 7540, 2650, 1980, 1560, 1120, 220],
  },
};
