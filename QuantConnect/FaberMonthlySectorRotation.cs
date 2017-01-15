using System;
using System.Collections.Generic;
using System.Linq;
using QuantConnect.Data.Market;
using QuantConnect.Indicators;
using QuantConnect.Orders;

namespace QuantConnect.Algorithm.Me
{
    public class FaberMonthlySectorRotation : QCAlgorithm
    {
        #region Properties
        bool extraCharting = false;
        int currentMonth = -1;
        DateTime lastProcessedDate = DateTime.MinValue;

        private Symbol spy = QuantConnect.Symbol.Create("SPY", SecurityType.Equity, Market.USA);
        SimpleMovingAverage spySma = null;

        //QuantConnect.ToolBox.exe "XLI,XLB,XLE,XLV,XLP,XLU,XLF,XLY,XLK,SPY" Daily 19980101 20161231
        List<string> SectorEtfSymbols = new List<string> { "XLI", "XLB", "XLE", "XLV", "XLP", "XLU", "XLF", "XLY", "XLK" };
        List<SymbolData> SectorEtfs = new List<SymbolData>();
        #endregion

        #region Initialize
        public override void Initialize()
        {
            SetCash(10000);
            SetStartDate(2010, 1, 1);
            SetEndDate(2016, 12, 31);

            AddEquity(spy.ID.Symbol, Resolution.Minute);
            spySma = SMA(spy, 200, Resolution.Daily);

            var history = History(spy, 201, Resolution.Daily);

            foreach (TradeBar tradeBar in history)
            {
                spySma.Update(tradeBar.EndTime, tradeBar.Close);
            }

            SetBenchmark(spy);

            foreach (var sym in SectorEtfSymbols)
            {
                //Symbol symbol = QuantConnect.Symbol.Create(sym, SecurityType.Equity, Market.USA);

                AddSecurity(SecurityType.Equity, sym, Resolution.Minute);
                var threeMonthPerformance = MOMP(sym, 60, Resolution.Daily);

                history = History(sym, 61, Resolution.Daily);

                foreach (TradeBar tradeBar in history)
                {
                    threeMonthPerformance.Update(tradeBar.EndTime, tradeBar.Close);
                }

                SectorEtfs.Add(new SymbolData
                {
                    Symbol = sym,
                    ThreeMonthPerformance = threeMonthPerformance
                });
            }

            Schedule.On(DateRules.EveryDay("SPY"), TimeRules.AfterMarketOpen(spy, 1), () =>
            {
                Allocate();
            });

            #region Charting
            if (extraCharting)
            {
                Chart stockPlot = new Chart("SPY");

                Series spyPriceSeries = new Series("Price", SeriesType.Line, 0);
                stockPlot.AddSeries(spyPriceSeries);

                Series spySmaSeries = new Series("SMA", SeriesType.Line, 0);
                stockPlot.AddSeries(spySmaSeries);

                Series buyingAllowedSeries = new Series("Buying Allowed", SeriesType.Line, 1);
                stockPlot.AddSeries(buyingAllowedSeries);

                AddChart(stockPlot);
            }
            #endregion
        }
        #endregion

        public void Allocate()
        {
            //TradeBar spyBar = data[spy];

            //if (extraCharting)
            //{
            //    Plot("SPY", "Price", data[spy].Close);
            //    Plot("SPY", "SMA", spySma);
            //    Plot("SPY", "Buying Allowed", data[spy].Close > spySma ? 1 : -1);
            //}

            if (currentMonth != Time.Month)
            {
                Log(String.Format("Allocate: {0}", Time.ToShortDateString()));

                TradeBar spyLast = History(spy, 1, Resolution.Daily).Last();

                currentMonth = Time.Month;

                if (spyLast.Close > spySma)
                {
                    List<String> topPerformers = this.SectorEtfs.OrderByDescending(x => x.ThreeMonthPerformance).Select(x => x.Symbol).Take(3).ToList();

                    foreach (Symbol x in Portfolio.Keys)
                    {
                        if (Portfolio[x].Invested && !topPerformers.Contains(x))
                        {
                            Liquidate(x);
                        }
                    }

                    foreach (String x in topPerformers)
                    {
                        SetHoldings(x, .333);
                    }
                }
                else
                {
                    Liquidate();
                }
            }
        }

        #region OnData
        public void OnData(TradeBars data)
        {
            
        }
        #endregion

        #region InitPerformanceChart
        public void InitPerformanceChart()
        {
            Chart chart = new Chart("Performance");

            Series spySeries = new Series("SPY", SeriesType.Line, 0);
            chart.AddSeries(spySeries);

            Series portfolioSeries = new Series("Portfolio", SeriesType.Line, 0);
            chart.AddSeries(portfolioSeries);

            Series exposure = new Series("Exposure", SeriesType.Line, 1);
            chart.AddSeries(exposure);

            AddChart(chart);
        }
        #endregion

        #region PlotPerformanceChart
        public void PlotPerformanceChart(TradeBar spyBar)
        {
            Plot("Performance", "SPY", spyBar.Close);
        }
        #endregion
    }

    class SymbolData
    {
        public String Symbol;
        public MomentumPercent ThreeMonthPerformance { get; set; }
    }
}