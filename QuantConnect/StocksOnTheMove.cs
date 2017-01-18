using System.Collections.Generic;
using System.Linq;
using QuantConnect.Data.Fundamental;
using QuantConnect.Data.Market;
using QuantConnect.Data.UniverseSelection;
using System;
using System.Collections.Concurrent;
using QuantConnect.Securities;
using QuantConnect.Indicators;
using QuantConnect.Data;

namespace QuantConnect.Algorithm.CSharp
{
    #region StocksOnTheMove
    public class StocksOnTheMove : QCAlgorithm
    {
        #region Properties
        bool webIde = false;
        private Symbol spy = QuantConnect.Symbol.Create("SPY", SecurityType.Equity, Market.USA);
        private SimpleMovingAverage spySma = null;
        private RiskAdjustedMomentum spyRamom = null;
        private MaximumGap spyMaxGap = null;
        private const int UniverseSize = 50;
        private const int NumberOfSymbolsFine = 2;
        private Decimal GapThreshold = .15m;
        int count = 0;
        private readonly ConcurrentDictionary<Symbol, String> stocks = new ConcurrentDictionary<Symbol, String>(); 
        #endregion

        #region Initialize
        public override void Initialize()
        {
            UniverseSettings.Resolution = Resolution.Daily;

            SetStartDate(2016, 01, 01);
            SetEndDate(2016, 12, 31);
            SetCash(15000);

            AddEquity(spy.ID.Symbol, webIde ? Resolution.Minute : Resolution.Daily);
            spySma = SMA(spy, 200);
            spyRamom = RAMOM(spy, 90);
            spyMaxGap = MAXGAP(spy, 90);

            var history = History(spy, 201, Resolution.Daily);

            foreach (TradeBar tradeBar in history)
            {
                spySma.Update(tradeBar.EndTime, tradeBar.Close);
            }

            foreach (TradeBar tradeBar in history.Skip(110))
            {
                spyRamom.Update(tradeBar.EndTime, tradeBar.Close);
                spyMaxGap.Update(tradeBar.EndTime, tradeBar.Close);
            }

            if (webIde)
            {
                AddUniverse(CoarseSelectionFunction);
            }

            Schedule.On(DateRules.Every(DayOfWeek.Wednesday), TimeRules.At(9, 31), () =>
            {
                Plot("Helper", "Count", stocks.Count);
                Plot("Helper", "SPY RAMOM", spyRamom);
                Plot("Helper", "SPY MAXGAP", spyMaxGap);
            });

            Chart stockPlot = new Chart("Helper");

            Series countSeries = new Series("Count", SeriesType.Line, 0);
            stockPlot.AddSeries(countSeries);

            Series spyRamomCountSeries = new Series("SPY RAMOM", SeriesType.Line, 1);
            stockPlot.AddSeries(spyRamomCountSeries);

            Series spyMaxGapCountSeries = new Series("SPY MAXGAP", SeriesType.Line, 2);
            stockPlot.AddSeries(spyMaxGapCountSeries);

            AddChart(stockPlot);
        } 
        #endregion

        #region Universe Stuff
        // sort the data by daily dollar volume and take the top 'NumberOfSymbolsCoarse'
        public IEnumerable<Symbol> CoarseSelectionFunction(IEnumerable<CoarseFundamental> coarse)
        {
            // select only symbols with fundamental data and sort descending by daily dollar volume
            var sortedByDollarVolume = coarse
                .Where(x => x.HasFundamentalData)
                .OrderByDescending(x => x.DollarVolume);

            // take the top entries from our sorted collection
            var top = sortedByDollarVolume.Take(UniverseSize);

            // we need to return only the symbol objects
            return top.Select(x => x.Symbol);
        }

        // sort the data by P/E ratio and take the top 'NumberOfSymbolsFine'
        public IEnumerable<Symbol> FineSelectionFunction(IEnumerable<FineFundamental> fine)
        {
            return fine.Select(x => x.Symbol);
        }
        #endregion

        #region OnData
        public void OnData(TradeBars data)
        {
            
        } 
        #endregion

        #region OnSecuritiesChanged
        public override void OnSecuritiesChanged(SecurityChanges changes)
        {
            if (changes.AddedSecurities.Count > 0)
            {
                foreach (Security security in changes.AddedSecurities)
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
        #endregion

        #region RAMOM
        public RiskAdjustedMomentum RAMOM(Symbol symbol, int period, Resolution? resolution = null, Func<IBaseData, decimal> selector = null)
        {
            string name = CreateIndicatorName(symbol, "RAMOM" + period, resolution);
            var riskAdjustedMomentum = new RiskAdjustedMomentum(name, period);
            RegisterIndicator(symbol, riskAdjustedMomentum, resolution, selector);
            return riskAdjustedMomentum;
        }
        #endregion

        #region MAXGAP
        public MaximumGap MAXGAP(Symbol symbol, int period, Resolution? resolution = null, Func<IBaseData, decimal> selector = null)
        {
            string name = CreateIndicatorName(symbol, "MAXGAP" + period, resolution);
            var maximumGap = new MaximumGap(name, period);
            RegisterIndicator(symbol, maximumGap, resolution, selector);
            return maximumGap;
        }
        #endregion
    }
    #endregion

    #region RiskAdjustedMomentum
    public class RiskAdjustedMomentum : WindowIndicator<IndicatorDataPoint>
    {
        /// <summary>
        /// Creates a new RateOfChange indicator with the specified period
        /// </summary>
        /// <param name="period">The period over which to perform to computation</param>
        public RiskAdjustedMomentum(int period)
            : base("RAMOM" + period, period)
        {
        }

        /// <summary>
        /// Creates a new RateOfChange indicator with the specified period
        /// </summary>
        /// <param name="name">The name of this indicator</param>
        /// <param name="period">The period over which to perform to computation</param>
        public RiskAdjustedMomentum(string name, int period)
            : base(name, period)
        {
        }

        /// <summary>
        /// Computes the next value for this indicator from the given state.
        /// </summary>
        /// <param name="window">The window of data held in this indicator</param>
        /// <param name="input">The input value to this indicator on this time step</param>
        /// <returns>A new value for this indicator</returns>
        protected override decimal ComputeNextValue(IReadOnlyWindow<IndicatorDataPoint> window, IndicatorDataPoint input)
        {
            // if we're not ready just grab the first input point in the window
            if (!window.IsReady)
            {
                return -1000m;
            }

            //newest -> oldest

            return ExponentialRegression(window);
        }

        public Decimal ExponentialRegression(IReadOnlyWindow<IndicatorDataPoint> window)
        {
            double sumOfX = 0;
            double sumOfY = 0;
            double sumOfXSq = 0;
            double sumOfYSq = 0;
            double ssX = 0;
            double ssY = 0;
            double sumCodeviates = 0;
            double sCo = 0;
            double count = window.Count;

            for (int ctr = 1; ctr <= count; ctr++)
            {
                double x = ctr;
                double y = Math.Log((double)window[(int)count - ctr].Value);
                sumCodeviates += x * y;
                sumOfX += x;
                sumOfY += y;
                sumOfXSq += x * x;
                sumOfYSq += y * y;
            }
            ssX = sumOfXSq - ((sumOfX * sumOfX) / count);
            ssY = sumOfYSq - ((sumOfY * sumOfY) / count);
            double RNumerator = (count * sumCodeviates) - (sumOfX * sumOfY);
            double RDenom = (count * sumOfXSq - (sumOfX * sumOfX))
             * (count * sumOfYSq - (sumOfY * sumOfY));
            sCo = sumCodeviates - ((sumOfX * sumOfY) / count);

            double meanX = sumOfX / count;
            double meanY = sumOfY / count;
            double dblR = RNumerator / Math.Sqrt(RDenom);
            double rsquared = dblR * dblR;
            double slope = sCo / ssX;
            double annualSlope = Math.Pow(1 + slope, 250.0) * rsquared * 100.0;

            return (Decimal)annualSlope;
        }
    }
    #endregion

    #region MaximumGap
    public class MaximumGap : WindowIndicator<IndicatorDataPoint>
    {
        /// <summary>
        /// Creates a new RateOfChange indicator with the specified period
        /// </summary>
        /// <param name="period">The period over which to perform to computation</param>
        public MaximumGap(int period)
            : base("MAXGAP" + period, period)
        {
        }

        /// <summary>
        /// Creates a new RateOfChange indicator with the specified period
        /// </summary>
        /// <param name="name">The name of this indicator</param>
        /// <param name="period">The period over which to perform to computation</param>
        public MaximumGap(string name, int period)
            : base(name, period)
        {
        }

        /// <summary>
        /// Computes the next value for this indicator from the given state.
        /// </summary>
        /// <param name="window">The window of data held in this indicator</param>
        /// <param name="input">The input value to this indicator on this time step</param>
        /// <returns>A new value for this indicator</returns>
        protected override decimal ComputeNextValue(IReadOnlyWindow<IndicatorDataPoint> window, IndicatorDataPoint input)
        {
            // if we're not ready just grab the first input point in the window
            if (!window.IsReady)
            {
                return 0;
            }

            //newest -> oldest
            Decimal max = 0;

            for (int i = 0; i < (window.Count - 1); i++)
            {
                max = Math.Max(max, Math.Abs((window[i].Value - window[i - 1].Value)/ window[i - 1].Value));
            }

            return max;
        }
    }
    #endregion
}