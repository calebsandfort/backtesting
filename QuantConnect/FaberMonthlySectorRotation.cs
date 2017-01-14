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
        DateTime LastRotationTime = new DateTime(1980, 1, 1);
        TimeSpan RotationInterval = TimeSpan.FromDays(30);

        private Symbol spy = QuantConnect.Symbol.Create("SPY", SecurityType.Equity, Market.USA);
        SimpleMovingAverage spySma = null;

        List<string> SectorEtfSymbols = new List<string> { "XLI", "XLB", "XLE", "XLV", "XLP", "XLU", "XLF", "XLY", "XLK" };
        List<SymbolData> SectorEtfs = new List<SymbolData>();

        public override void Initialize()
        {
            SetCash(10000);
            SetStartDate(2012, 1, 3);
            SetEndDate(2016, 12, 31);

            SetWarmUp(TimeSpan.FromDays(300));

            AddEquity(spy.ID.Symbol, Resolution.Daily);
            spySma = SMA(spy, 300, Resolution.Daily);
            SetBenchmark("SPY");

            foreach (var sym in SectorEtfSymbols)
            {
                //Symbol symbol = QuantConnect.Symbol.Create(sym, SecurityType.Equity, Market.USA);

                AddSecurity(SecurityType.Equity, sym, Resolution.Daily);
                var threeMonthPerformance = MOM(sym, 90, Resolution.Daily);

                SectorEtfs.Add(new SymbolData
                {
                    Symbol = sym,
                    ThreeMonthPerformance = threeMonthPerformance
                });
            }

            #region Charting
            Chart stockPlot = new Chart("SPY");

            Series spyPriceSeries = new Series("Price", SeriesType.Line, 0);
            stockPlot.AddSeries(spyPriceSeries);

            //Series spySmaSeries = new Series("SMA", SeriesType.Line, 0);
            //stockPlot.AddSeries(spySmaSeries);

            //Series buyingAllowedSeries = new Series("Buying Allowed", SeriesType.Line, 1);
            //stockPlot.AddSeries(buyingAllowedSeries);

            AddChart(stockPlot);
            #endregion
        }

        public void OnData(TradeBars data)
        {
            if (!this.IsWarmingUp)
            {
                TradeBar spyBar = data[spy];
                Plot("SPY", "Price", data[spy].Close);
                //Plot("SPY", "SMA", spySma);
                //Plot("SPY", "Buying Allowed", data[spy].Close > spySma ? 1 : -1);
                var delta = Time.Subtract(LastRotationTime);
                if (delta > RotationInterval)
                {
                    LastRotationTime = Time;

                    if (data[spy].Close > spySma)
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
        }
    }

    class SymbolData
    {
        public String Symbol;
        public Momentum ThreeMonthPerformance { get; set; }
    }
}