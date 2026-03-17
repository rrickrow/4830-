/**
 * fallback-data.js
 *
 * Real historical data sourced from World Bank Open Data
 * (https://data.worldbank.org/), used as offline fallback
 * when the API is not reachable.
 *
 * License: CC BY 4.0  https://datacatalog.worldbank.org/public-licenses#cc-by
 * Retrieved: 2024
 */
window.WB_FALLBACK = {
  // NY.GDP.MKTP.CD — China GDP, current US$
  gdp: [
    {year:1990,value:3.607e11},{year:1991,value:4.094e11},{year:1992,value:4.888e11},
    {year:1993,value:6.131e11},{year:1994,value:5.592e11},{year:1995,value:7.341e11},
    {year:1996,value:8.632e11},{year:1997,value:9.616e11},{year:1998,value:1.029e12},
    {year:1999,value:1.094e12},{year:2000,value:1.211e12},{year:2001,value:1.340e12},
    {year:2002,value:1.471e12},{year:2003,value:1.661e12},{year:2004,value:1.955e12},
    {year:2005,value:2.286e12},{year:2006,value:2.752e12},{year:2007,value:3.552e12},
    {year:2008,value:4.598e12},{year:2009,value:5.102e12},{year:2010,value:6.087e12},
    {year:2011,value:7.551e12},{year:2012,value:8.532e12},{year:2013,value:9.571e12},
    {year:2014,value:1.047e13},{year:2015,value:1.107e13},{year:2016,value:1.123e13},
    {year:2017,value:1.231e13},{year:2018,value:1.388e13},{year:2019,value:1.429e13},
    {year:2020,value:1.468e13},{year:2021,value:1.773e13},{year:2022,value:1.796e13},
  ],

  // NY.GDP.MKTP.KD.ZG — China GDP growth rate, annual %
  gdpGrowth: [
    {year:1985,value:13.50},{year:1986,value:8.87},{year:1987,value:11.60},
    {year:1988,value:11.30},{year:1989,value:4.20},{year:1990,value:3.92},
    {year:1991,value:9.18},{year:1992,value:14.24},{year:1993,value:13.96},
    {year:1994,value:13.08},{year:1995,value:10.93},{year:1996,value:9.93},
    {year:1997,value:9.23},{year:1998,value:7.85},{year:1999,value:7.67},
    {year:2000,value:8.49},{year:2001,value:8.34},{year:2002,value:9.08},
    {year:2003,value:10.03},{year:2004,value:10.11},{year:2005,value:11.39},
    {year:2006,value:12.72},{year:2007,value:14.23},{year:2008,value:9.65},
    {year:2009,value:9.40},{year:2010,value:10.64},{year:2011,value:9.49},
    {year:2012,value:7.75},{year:2013,value:7.76},{year:2014,value:7.30},
    {year:2015,value:6.90},{year:2016,value:6.74},{year:2017,value:6.95},
    {year:2018,value:6.75},{year:2019,value:5.95},{year:2020,value:2.24},
    {year:2021,value:8.45},{year:2022,value:3.00},
  ],

  // SP.POP.TOTL — China population total
  pop: [
    {year:1980,value:9.813e8},{year:1981,value:1.000e9},{year:1982,value:1.016e9},
    {year:1983,value:1.030e9},{year:1984,value:1.044e9},{year:1985,value:1.058e9},
    {year:1986,value:1.075e9},{year:1987,value:1.093e9},{year:1988,value:1.111e9},
    {year:1989,value:1.127e9},{year:1990,value:1.143e9},{year:1991,value:1.158e9},
    {year:1992,value:1.172e9},{year:1993,value:1.185e9},{year:1994,value:1.199e9},
    {year:1995,value:1.211e9},{year:1996,value:1.224e9},{year:1997,value:1.236e9},
    {year:1998,value:1.248e9},{year:1999,value:1.259e9},{year:2000,value:1.263e9},
    {year:2001,value:1.271e9},{year:2002,value:1.280e9},{year:2003,value:1.288e9},
    {year:2004,value:1.296e9},{year:2005,value:1.304e9},{year:2006,value:1.312e9},
    {year:2007,value:1.321e9},{year:2008,value:1.328e9},{year:2009,value:1.335e9},
    {year:2010,value:1.340e9},{year:2011,value:1.347e9},{year:2012,value:1.354e9},
    {year:2013,value:1.360e9},{year:2014,value:1.368e9},{year:2015,value:1.375e9},
    {year:2016,value:1.383e9},{year:2017,value:1.390e9},{year:2018,value:1.395e9},
    {year:2019,value:1.400e9},{year:2020,value:1.412e9},{year:2021,value:1.412e9},
    {year:2022,value:1.412e9},
  ],

  // SP.URB.TOTL.IN.ZS — Urban population (% of total)
  urban: [
    {year:1980,value:19.39},{year:1981,value:20.16},{year:1982,value:21.13},
    {year:1983,value:21.62},{year:1984,value:22.58},{year:1985,value:23.71},
    {year:1986,value:24.52},{year:1987,value:25.32},{year:1988,value:25.81},
    {year:1989,value:26.21},{year:1990,value:26.41},{year:1991,value:27.38},
    {year:1992,value:28.46},{year:1993,value:29.61},{year:1994,value:30.90},
    {year:1995,value:31.04},{year:1996,value:32.53},{year:1997,value:33.82},
    {year:1998,value:35.04},{year:1999,value:36.35},{year:2000,value:35.89},
    {year:2001,value:37.66},{year:2002,value:39.09},{year:2003,value:40.53},
    {year:2004,value:41.76},{year:2005,value:42.99},{year:2006,value:44.34},
    {year:2007,value:45.89},{year:2008,value:47.05},{year:2009,value:48.34},
    {year:2010,value:49.95},{year:2011,value:51.27},{year:2012,value:52.57},
    {year:2013,value:53.73},{year:2014,value:54.77},{year:2015,value:55.60},
    {year:2016,value:57.35},{year:2017,value:58.52},{year:2018,value:59.58},
    {year:2019,value:60.60},{year:2020,value:61.43},{year:2021,value:62.48},
    {year:2022,value:63.60},
  ],

  // NY.GDP.PCAP.CD — Per capita GDP, current US$
  gdpPc: [
    {year:1990,value:317},{year:1991,value:354},{year:1992,value:423},
    {year:1993,value:531},{year:1994,value:473},{year:1995,value:611},
    {year:1996,value:709},{year:1997,value:787},{year:1998,value:828},
    {year:1999,value:873},{year:2000,value:960},{year:2001,value:1058},
    {year:2002,value:1150},{year:2003,value:1290},{year:2004,value:1508},
    {year:2005,value:1755},{year:2006,value:2100},{year:2007,value:2695},
    {year:2008,value:3471},{year:2009,value:3832},{year:2010,value:4560},
    {year:2011,value:5618},{year:2012,value:6317},{year:2013,value:7078},
    {year:2014,value:7683},{year:2015,value:8069},{year:2016,value:8117},
    {year:2017,value:8879},{year:2018,value:9977},{year:2019,value:10218},
    {year:2020,value:10435},{year:2021,value:12556},{year:2022,value:12720},
  ],

  // NE.EXP.GNFS.CD — Exports of goods and services, current US$
  exports: [
    {year:1990,value:7.16e10},{year:1991,value:8.64e10},{year:1992,value:1.02e11},
    {year:1993,value:1.05e11},{year:1994,value:1.31e11},{year:1995,value:1.73e11},
    {year:1996,value:1.89e11},{year:1997,value:2.26e11},{year:1998,value:2.21e11},
    {year:1999,value:2.35e11},{year:2000,value:2.93e11},{year:2001,value:3.00e11},
    {year:2002,value:3.68e11},{year:2003,value:4.80e11},{year:2004,value:6.57e11},
    {year:2005,value:8.37e11},{year:2006,value:1.05e12},{year:2007,value:1.34e12},
    {year:2008,value:1.62e12},{year:2009,value:1.33e12},{year:2010,value:1.77e12},
    {year:2011,value:2.24e12},{year:2012,value:2.37e12},{year:2013,value:2.59e12},
    {year:2014,value:2.76e12},{year:2015,value:2.59e12},{year:2016,value:2.41e12},
    {year:2017,value:2.62e12},{year:2018,value:2.86e12},{year:2019,value:2.72e12},
    {year:2020,value:2.73e12},{year:2021,value:3.55e12},{year:2022,value:3.71e12},
  ],

  // NE.IMP.GNFS.CD — Imports of goods and services, current US$
  imports: [
    {year:1990,value:6.54e10},{year:1991,value:7.58e10},{year:1992,value:9.47e10},
    {year:1993,value:1.21e11},{year:1994,value:1.22e11},{year:1995,value:1.62e11},
    {year:1996,value:1.69e11},{year:1997,value:1.73e11},{year:1998,value:1.73e11},
    {year:1999,value:1.82e11},{year:2000,value:2.50e11},{year:2001,value:2.60e11},
    {year:2002,value:3.26e11},{year:2003,value:4.65e11},{year:2004,value:6.40e11},
    {year:2005,value:7.36e11},{year:2006,value:8.68e11},{year:2007,value:1.10e12},
    {year:2008,value:1.44e12},{year:2009,value:1.17e12},{year:2010,value:1.62e12},
    {year:2011,value:2.04e12},{year:2012,value:2.13e12},{year:2013,value:2.34e12},
    {year:2014,value:2.44e12},{year:2015,value:2.21e12},{year:2016,value:2.04e12},
    {year:2017,value:2.29e12},{year:2018,value:2.56e12},{year:2019,value:2.55e12},
    {year:2020,value:2.46e12},{year:2021,value:3.24e12},{year:2022,value:3.30e12},
  ],

  // EN.ATM.CO2E.KT — CO2 emissions (kt) — World Bank/IEA data
  co2: [
    {year:1990,value:2.460e6},{year:1991,value:2.566e6},{year:1992,value:2.637e6},
    {year:1993,value:2.763e6},{year:1994,value:2.918e6},{year:1995,value:3.128e6},
    {year:1996,value:3.255e6},{year:1997,value:3.241e6},{year:1998,value:3.188e6},
    {year:1999,value:3.140e6},{year:2000,value:3.316e6},{year:2001,value:3.405e6},
    {year:2002,value:3.616e6},{year:2003,value:4.200e6},{year:2004,value:4.832e6},
    {year:2005,value:5.414e6},{year:2006,value:5.968e6},{year:2007,value:6.479e6},
    {year:2008,value:6.801e6},{year:2009,value:7.119e6},{year:2010,value:7.723e6},
    {year:2011,value:8.671e6},{year:2012,value:8.965e6},{year:2013,value:9.298e6},
    {year:2014,value:9.246e6},{year:2015,value:9.045e6},{year:2016,value:9.004e6},
    {year:2017,value:9.202e6},{year:2018,value:9.570e6},{year:2019,value:9.826e6},
    {year:2020,value:9.899e6},
  ],

  // Multi-country GDP 2022 comparison (NY.GDP.MKTP.CD, current US$)
  compareGDP: [
    {countryiso3code:"USA", country:{id:"US",value:"United States"},  value:2.570e13},
    {countryiso3code:"CHN", country:{id:"CN",value:"China"},          value:1.796e13},
    {countryiso3code:"JPN", country:{id:"JP",value:"Japan"},          value:4.232e12},
    {countryiso3code:"DEU", country:{id:"DE",value:"Germany"},        value:4.072e12},
    {countryiso3code:"IND", country:{id:"IN",value:"India"},          value:3.385e12},
    {countryiso3code:"GBR", country:{id:"GB",value:"United Kingdom"}, value:3.071e12},
    {countryiso3code:"FRA", country:{id:"FR",value:"France"},         value:2.779e12},
    {countryiso3code:"CAN", country:{id:"CA",value:"Canada"},         value:2.140e12},
    {countryiso3code:"ITA", country:{id:"IT",value:"Italy"},          value:1.997e12},
    {countryiso3code:"KOR", country:{id:"KR",value:"Korea, Rep."},    value:1.665e12},
  ],
};
