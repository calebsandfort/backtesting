using System.Collections.Generic;
using System.Linq;
using QuantConnect.Data.Fundamental;
using QuantConnect.Data.Market;
using QuantConnect.Data.UniverseSelection;
using System;
using System.Collections.Concurrent;
using QuantConnect.Securities;
using QuantConnect.Indicators;

namespace QuantConnect.Algorithm.CSharp
{
    public class StocksOnTheMove : QCAlgorithm
    {
        bool webIde = false;
        private Symbol spy = QuantConnect.Symbol.Create("SPY", SecurityType.Equity, Market.USA);
        private MomentumPercent spyMomp = null;
        private const int NumberOfSymbolsCoarse = 50;
        private const int NumberOfSymbolsFine = 2;
        int count = 0;
        private readonly ConcurrentDictionary<Symbol, String> stocks = new ConcurrentDictionary<Symbol, String>();

        public override void Initialize()
        {
            UniverseSettings.Resolution = Resolution.Daily;

            SetStartDate(2016, 01, 01);
            SetEndDate(2016, 12, 31);
            SetCash(20000);

            AddEquity(spy.ID.Symbol, webIde ? Resolution.Minute : Resolution.Daily);
            spyMomp = MOMP(spy, 60);

            //var history = History(spy, 61, Resolution.Daily);

            //foreach (TradeBar tradeBar in history)
            //{
            //    spyMomp.Update(tradeBar.EndTime, tradeBar.Close);
            //}

            //if (webIde)
            //{
            //    AddUniverse(CoarseSelectionFunction);
            //}

            Schedule.On(DateRules.Every(DayOfWeek.Wednesday), TimeRules.At(9, 31), () =>
            {
                Plot("Helper", "Count", stocks.Count);
            });

            Chart stockPlot = new Chart("Helper");

            Series countSeries = new Series("Count", SeriesType.Line, 0);
            stockPlot.AddSeries(countSeries);

            AddChart(stockPlot);
        }

        #region Universe Stuff
        // sort the data by daily dollar volume and take the top 'NumberOfSymbolsCoarse'
        public IEnumerable<Symbol> CoarseSelectionFunction(IEnumerable<CoarseFundamental> coarse)
        {
            // select only symbols with fundamental data and sort descending by daily dollar volume
            var sortedByDollarVolume = coarse
                .Where(x => x.HasFundamentalData)
                .OrderByDescending(x => x.DollarVolume);

            // take the top entries from our sorted collection
            var top = sortedByDollarVolume.Take(NumberOfSymbolsCoarse);

            // we need to return only the symbol objects
            return top.Select(x => x.Symbol);
        }

        // sort the data by P/E ratio and take the top 'NumberOfSymbolsFine'
        public IEnumerable<Symbol> FineSelectionFunction(IEnumerable<FineFundamental> fine)
        {
            return fine.Select(x => x.Symbol);
        }
        #endregion

        public void OnData(TradeBars data)
        {
            if (spyMomp.IsReady)
            {
                Log(String.Format("Ready: {0}", Time.ToShortDateString()));
            }
        }

        public override void OnSecuritiesChanged(SecurityChanges changes)
        {
            if (changes.AddedSecurities.Count > 0)
            {
                foreach(Security security in changes.AddedSecurities)
                {
                    stocks.AddOrUpdate(security.Symbol, security.Symbol.ID.Symbol);
                }

                count += changes.AddedSecurities.Count;
            }

            if (changes.RemovedSecurities.Count > 0)
            {
                String temp = String.Empty;

                foreach (Security security in changes.RemovedSecurities)
                {
                    if (stocks.ContainsKey(security.Symbol))
                    {
                        stocks.TryRemove(security.Symbol, out temp);
                    }
                }
                count -= changes.RemovedSecurities.Count;
            }
        }
    }
}