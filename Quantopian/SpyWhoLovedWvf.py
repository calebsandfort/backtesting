import numpy as np
import scipy
import pandas as pd
import time  
from datetime import datetime  
from pytz import timezone
import talib
import math
from scipy import stats

def initialize(context):
    set_slippage(slippage.FixedSlippage(spread=0))
    #set_slippage(slippage.VolumeShareSlippage(volume_limit=1, price_impact=0))
    
    context.bullish_stock = sid(39214) #TQQQ
    context.bearish_stock = sid(38294) #TMF
    context.vxx = sid(38054) #VXX -> Vix Bull
    context.xiv = sid(40516) #XIV -> VIX Bear
    context.safe_harbor_stock = sid(32841) #RHS
    
    context.stocks = [context.bullish_stock,
                      context.bearish_stock,
                      context.xiv
                     ]
    context.n = 0
    context.s = np.zeros_like(context.stocks)
    context.x0 = np.zeros_like(context.stocks)
    context.x1 = 1.0*np.ones_like(context.stocks)/len(context.stocks)
    
    context.eps = 0.01
    context.tol = 1.0e-6    #assume convergence is 10 time SLSQP ftol of 1e-6
    context.valid_constraint_count = 0
    context.opt_pass_count = 0
    context.run_count = 0
    context.eps_vals = []
    
    context.weekly_buys = {}
    context.spy_buys = {}
    
    context.RISK_LEVEL = 1.0
    context.PIGGY_BANK = 500
    context.SAFE_HARBOR = 3000
    context.CHG_PERIOD = 10
    context.RAMOM_PERIOD = 14
    context.MAX_LOSS = -.175
    context.LOST_PAUSE_INTERVAL = 2
    context.lost_pause_counter = 0
    context.is_first_of_week = False   
    context.is_trading_day = False   
    
    schedule_function(set_is_first_of_week,date_rules.week_start(),time_rules.market_open())
    schedule_function(set_is_trading_day,date_rules.week_start(1),time_rules.market_open())
    
    schedule_function(func = allocVOL, date_rule = date_rules.every_day(), time_rule = time_rules.market_open(minutes = 15))  
    
    schedule_function(allocate,date_rules.every_day(),time_rules.market_open(minutes=60))    
    schedule_function(trade_weekly_sells,date_rules.week_start(1),time_rules.market_open(minutes=60))  
    
    for i in range(0, 13):
        offset = 60 + (i * 5)
        schedule_function(trade_weekly_buys,date_rules.week_start(1),time_rules.market_open(minutes=offset))

    schedule_function(func = trade_spy_sell, date_rule = date_rules.every_day(), time_rule = time_rules.market_close(minutes = 20))
    schedule_function(func = trade_spy_buy, date_rule = date_rules.every_day(), time_rule = time_rules.market_close(minutes = 15))
    schedule_function(func = trade_spy_buy, date_rule = date_rules.every_day(), time_rule = time_rules.market_close(minutes = 10))
    schedule_function(func = trade_spy_buy, date_rule = date_rules.every_day(), time_rule = time_rules.market_close(minutes = 5))
    
    set_long_only()
    
    #Reporting
    context.total_trades = 0
    context.vxx_wfv = 0
    context.portfolio_tracker = []
    
    context.position_stats = pd.DataFrame(columns=["Days Held", "Avg Size"])
    
    schedule_function(record_leverage, date_rules.every_day(), time_rules.market_close())
    schedule_function(record_portfolio_stats, date_rules.every_day(), time_rules.market_close(minutes=60))
    schedule_function(final_reporting, date_rules.every_day(), time_rules.market_close())

def set_is_first_of_week(context, data):
    context.is_first_of_week = True

def set_is_trading_day(context, data):
    context.is_trading_day = True
    
    if context.safe_harbor_stock not in context.portfolio.positions:
        order(context.safe_harbor_stock, int(context.SAFE_HARBOR/data.current(context.safe_harbor_stock, "price")))

def record_portfolio_stats(context, data):
    for pos in context.portfolio.positions:
        if pos not in context.position_stats.index:
            df = pd.DataFrame({"Days Held": 0, "Avg Size": 0.0}, index=[pos]);
            context.position_stats = context.position_stats.append(df);
        
        context.position_stats.loc[pos]["Avg Size"] = ((context.position_stats.loc[pos]["Avg Size"] * context.position_stats.loc[pos]["Days Held"]) + get_position_size(context, data, pos))/(context.position_stats.loc[pos]["Days Held"] + 1)
        context.position_stats.loc[pos]["Days Held"] += 1
    
def record_leverage(context, data):
    #record(cash = 1 if context.portfolio.cash < 0 else 0)
    #record(total_trades = context.total_trades)

    #context.mx_lvrg = 0
    context.is_trading_day = False
    context.is_first_of_week = False

def final_reporting(context, data):
    if len(context.weekly_buys) > 0 or len(context.spy_buys) > 0:
        log.info("Open Buy Orders")
    
    if is_date(2017, 1, 25):
        log.info("Total trades: %d" % context.total_trades)
        
        log.info ("\n%s" % "\n".join(["%s: Days Held: %d, Avg Size: %0.4f" % (stock.symbol, row["Days Held"], row["Avg Size"]) for stock, row in context.position_stats.iterrows()]))
        # log.info("*************************************************************")
        # log.info("\n")
    
def place_order(context, data, stock, percent):
    shares = get_shares(context, data, stock, percent)
    current_shares = 0
    
    if stock in context.portfolio.positions:
        current_shares = context.portfolio.positions[stock].amount
        
    if shares != current_shares:
        context.total_trades += 1
    
    order_target_percent(stock, percent)

def get_shares(context, data, stock, percent):
    current_price = data.current(stock, "price")
    shares = int((context.portfolio.portfolio_value * percent)/current_price)
    return shares
 
def get_position_size(context, data, stock):
    if stock not in context.portfolio.positions:
        return 0.0
    
    pos = context.portfolio.positions[stock]
    
    return (pos.amount * pos.last_sale_price) / context.portfolio.portfolio_value

def get_target_position_size(context, data, position_size):
    return (get_adjusted_portfolio_size(context)/context.portfolio.portfolio_value)*position_size*context.RISK_LEVEL

def get_adjusted_portfolio_size(context):
    safe_harbor_value = context.portfolio.positions[context.safe_harbor_stock].amount * context.portfolio.positions[context.safe_harbor_stock].last_sale_price
    # safe_harbor_value = 0
    
    return context.portfolio.portfolio_value - safe_harbor_value - context.PIGGY_BANK
    
def get_net_shares(context, data, stock, target_size):
    existing_shares = 0
    
    if stock in context.portfolio.positions:
        existing_shares = context.portfolio.positions[stock].amount
        
    target_shares = int((context.portfolio.portfolio_value * target_size) / data.current(stock, "price"))
    
    return target_shares - existing_shares
    
def allocate(context, data):     
    context.run_count += 1
    prices = data.history(context.stocks, 'price', 17*390,'1m')
    ret = prices.pct_change()[1:].as_matrix(context.stocks)
    ret_mean = prices.pct_change().mean()
    ret_std = prices.pct_change().std()
    ret_norm = ret_mean/ret_std
    ret_norm = ret_norm.as_matrix(context.stocks)
    ret_norm_max = np.max(ret_norm)
    eps_factor = 0.9 if ret_norm_max >0 else 1.0
    context.eps = eps_factor*ret_norm_max
    
    bnds = []
    limits = [0,1]
    
    for stock in context.stocks:
        bnds.append(limits)
           
    bnds = tuple(tuple(x) for x in bnds)

    cons = ({'type': 'eq', 'fun': lambda x:  np.sum(x)-1.0},
            {'type': 'ineq', 'fun': lambda x:  np.dot(x,ret_norm)-context.eps})
    
    res= scipy.optimize.minimize(variance, context.x1, args=ret,jac=jac_variance, method='SLSQP',constraints=cons,bounds=bnds)

    allocation = np.copy(context.x0)    
    if res.success:    # if SLSQP declares success
        context.opt_pass_count += 1
        
        weighted_ret_norm = np.dot(res.x,ret_norm)
        w_ret_constraint = weighted_ret_norm - context.eps + context.tol
       
        if(w_ret_constraint > 0): # and constraint is actually met
            context.valid_constraint_count += 1
            allocation = res.x
            allocation[allocation<0] = 0
            denom = np.sum(allocation)
            if denom > 0:
                allocation = allocation/denom 
                
            # msg = "{0} runs, {1} SLSQP passes, {2} constraints passed".format(
            #     context.run_count, context.opt_pass_count,
            #     context.valid_constraint_count)
            #if(context.run_count>1000): log.info(msg)
        else:
            pass
            # log.info("constraint fail, SLSQP status = {0}".format(res.status))
    else:
        pass
        # log.info("SLSQP fail, SLSQP status = {0}".format(res.status))
    context.n += 1
    context.s += allocation

def trade_weekly_sells(context, data):
    if context.n > 0:
        allocation = context.s/context.n
    else:
        return
    
    context.n = 0
    context.s = np.zeros_like(context.stocks)
    context.x0 = allocation
    
    if is_date(2013, 12, 3) or get_open_orders():
        return
    
    if context.lost_pause_counter > 0:
        context.lost_pause_counter -= 1
        return
    
    for i,stock in enumerate(context.stocks):
        net_shares = get_net_shares(context, data, stock, get_target_position_size(context, data, allocation[i]))

        if net_shares < 0:
            place_order(context, data, stock, get_target_position_size(context, data, allocation[i]))
        elif net_shares > 0:
            context.weekly_buys[stock] = get_target_position_size(context, data, allocation[i])
                       
    # log.info (", ".join(["%s %0.3f" % (stock.symbol, allocation[i]) for i,stock in enumerate(context.stocks)]))
    # log.info("*************************************************************")
    # log.info("\n")

def trade_weekly_buys(context, data):
    if len(context.weekly_buys) is 0 or (len(context.weekly_buys) > 0 and get_open_orders()):
        #log.info("trade_weekly_buys: Open Sell Orders")
        return
    
    for stock in context.weekly_buys:
        place_order(context, data, stock, context.weekly_buys[stock])
    
    context.weekly_buys = {}

def allocVOL(context, data):    
    if context.is_trading_day:
        return
    
    vxx = context.vxx
    xiv = context.xiv
    WFV_limit= 14 #(Kory used 14 but it becomes a bit too agressive)
    n = 28
    vxx_prices = data.history(vxx, "price", n + 2, "1d")[:-1]
    vxx_lows = data.history(vxx, "low", n + 2, "1d")[:-1]
    #vxx_highest = pd.rolling_max(vxx_prices, window = n)    
    vxx_highest = vxx_prices.rolling(window = n, center=False).max()
    
    #William's VIX Fix indicator a.k.a. the Synthetic VIX
    WVF = ((vxx_highest - vxx_lows)/(vxx_highest)) * 100

    context.vxx_price = data.current(vxx, "price")
    context.vxx_wfv = WVF[-1]
    
    #Sell position when WVF crosses under 14
    if(WVF[-2] > WFV_limit and WVF[-1] <= WFV_limit):
        order_target_percent(xiv, 0.00)   

def get_ramom(context, prices):
    X = range(0, len(prices))
    # Y = np.log(prices)
    Y = prices
    a_s,b_s,r,tt,stderr=stats.linregress(X,Y)
    
    ramom = math.pow(1.0 + a_s, context.RAMOM_PERIOD) * r * r
    
    return ramom, a_s, r * r
        
def trade_spy_sell (context, data):  
    # context.portfolio_tracker.append(get_adjusted_portfolio_size(context))
    
    # max_pv = np.max(context.portfolio_tracker)
    # chg = (context.portfolio_tracker[-1] - max_pv)/max_pv
    # if chg < context.MAX_LOSS and not context.is_trading_day:
    #     log.info("%.3f%% loss" % context.MAX_LOSS)
    #     context.lost_pause_counter = context.LOST_PAUSE_INTERVAL
    #     context.portfolio_tracker = []
        
    #     for pos in context.portfolio.positions:
    #         if pos != context.safe_harbor_stock:
    #             order_target_percent(pos, 0)
                
    #     return
                            
    if context.is_trading_day or context.is_first_of_week:
        return
    
    bullish_size = get_position_size(context, data, context.bullish_stock)
    bearish_size = get_position_size(context, data, context.bearish_stock)

    bullish_change = spy_change_logic(context, data, context.bullish_stock)

    if (bullish_change and bearish_size > bullish_size) or (not bullish_change and bullish_size > bearish_size):
        bearish_net_shares = get_net_shares(context, data, context.bearish_stock, bullish_size)
        bullish_net_shares = get_net_shares(context, data, context.bullish_stock, bearish_size)
        
        if bearish_net_shares > 0 and bullish_net_shares < 0:
            place_order(context, data, context.bullish_stock, bearish_size)
            context.spy_buys[context.bearish_stock] = bullish_size
        elif bearish_net_shares < 0 and bullish_net_shares > 0:
            place_order(context, data, context.bearish_stock, bullish_size)
            context.spy_buys[context.bullish_stock] = bearish_size
        elif bearish_net_shares != 0 and bullish_net_shares == 0:
            place_order(context, data, context.bearish_stock, bullish_size)
        
def trade_spy_buy (context, data):  
    if len(context.spy_buys) == 0 or (len(context.spy_buys) > 0 and get_open_orders()):
        #log.info("trade_spy_buy: Open Sell Orders")
        return
    
    for stock in context.spy_buys:
        place_order(context, data, stock, context.spy_buys[stock])
    
    context.spy_buys = {}
        
def is_date(year, month, day):
    date = get_datetime()
    return date.year == year and date.month == month and date.day == day

def spy_change_logic(context, data, stock):
    ####Inputs Tab Criteria.
    period      = 28 #"LookBack Period Standard Deviation High")
    bbl     = 22 # "Bolinger Band Length")
    mult    = 1.05 # "Bollinger Band Standard Devaition Up")
    lb      = 22   # "Look Back Period Percentile High")
    ph      = .90# "Highest Percentile - 0.90=90%, 0.95=95%, 0.99=99%")

    #Criteria for Down Trend Definition for Filtered Pivots and Aggressive Filtered Pivots
    ltLB    = 40 # Long-Term Look Back Current Bar Has To Close Below This Value OR Medium Term--Default=40")
    mtLB    = 14 # Medium-Term Look Back Current Bar Has To Close Below This Value OR Long Term--Default=14")
    Str     = 3  # Entry Price Action Strength--Close > X Bars Back---Default=3")

    spy_close = data.history(stock, "close", 2*period + 2, "1d")
    spy_prices = data.history(stock, "price", 2*period + 2, "1d")
    spy_lows = data.history(stock, "low", 2*period + 2, "1d")
    spy_highest = spy_prices.rolling(window = period).max()    
    
    #Williams Vix Fix Formula
    wvf = ((spy_highest - spy_lows)/(spy_highest)) * 100
    sDev = mult * np.std(wvf[-bbl:])
    midLine = np.mean(wvf[-bbl:])
    upperBand = midLine + sDev
    rangeHigh = (max(wvf[-lb:])) * ph

    spy_higher_then_Xdays_back = spy_close[-1] > spy_close[-Str]
    spy_lower_then_longterm = spy_close[-1] < spy_close[-ltLB]
    spy_lower_then_midterm = spy_close[-1] < spy_close[-mtLB]
    
    #Alerts Criteria
    alert2 = not (wvf[-1] >= upperBand and wvf[-1] >= rangeHigh) and (wvf[-2] >= upperBand and wvf[-2] >= rangeHigh)
    
    return (alert2 or spy_higher_then_Xdays_back) and (spy_lower_then_longterm or spy_lower_then_midterm)

# def handle_data(context, data):  
#     if 'mx_lvrg' not in context:             # Max leverage  
#         context.mx_lvrg = 0                  # Init this instead in initialize() for better efficiency  
#     if context.account.leverage > context.mx_lvrg:  
#         context.mx_lvrg = context.account.leverage  
#         #record(mx_lvrg = context.mx_lvrg)

def handle_data(context, data):  
    pvr(context, data)

def pvr(context, data):  
    ''' Custom chart and/or log of profit_vs_risk returns and related information  
    '''  
    # # # # # # # # # #  Options  # # # # # # # # # #  
    record_pvr      = 1            # Profit vs Risk returns (percentage)  
    record_pvrp     = 0            # PvR (p)roportional neg cash vs portfolio value  
    record_cash     = 0            # Cash available  
    record_max_lvrg = 1            # Maximum leverage encountered  
    record_risk_hi  = 1            # Highest risk overall  
    record_shorting = 0            # Total value of any shorts  
    record_cash_low = 1            # Any new lowest cash level  
    record_q_return = 0            # Quantopian returns (percentage)  
    record_pnl      = 0            # Profit-n-Loss  
    record_risk     = 0            # Risked, max cash spent or shorts beyond longs+cash  
    record_leverage = 0            # Leverage (context.account.leverage)  
    record_overshrt = 0            # Shorts beyond longs+cash  
    logging         = 0            # Also to logging window conditionally (1) or not (0)  
    if record_pvrp: record_pvr = 0 # if pvrp is active, straight pvr is off
 
    c = context  # Brevity is the soul of wit -- Shakespeare [for efficiency, readability]  
    if 'pvr' not in c:  
        date_strt = get_environment('start').date()  
        date_end  = get_environment('end').date()  
        cash_low  = c.portfolio.starting_cash  
        c.cagr    = 0.0  
        c.pvr     = {  
            'pvr'        : 0,      # Profit vs Risk returns based on maximum spent  
            'max_lvrg'   : 0,  
            'risk_hi'    : 0,  
            'days'       : 0.0,  
            'date_prv'   : '',  
            'date_end'   : date_end,  
            'cash_low'   : cash_low,  
            'cash'       : cash_low,  
            'start'      : cash_low,  
            'begin'      : time.time(),  # For run time  
            'log_summary': 126,          # Summary every x days  
            'run_str'    : '{} to {}  ${}  {} US/Eastern'.format(date_strt, date_end, int(cash_low), datetime.now(timezone('US/Eastern')).strftime("%Y-%m-%d %H:%M"))  
        }  
        log.info(c.pvr['run_str'])

    def _pvr_(c):  
        c.cagr = ((c.portfolio.portfolio_value / c.pvr['start']) ** (1 / (c.pvr['days'] / 252.))) - 1  
        ptype = 'PvR' if record_pvr else 'PvRp'  
        log.info('{} {} %/day   cagr {}'.format(ptype, '%.4f' % (c.pvr['pvr'] / c.pvr['days']), '%.1f' % c.cagr))  
        log.info('  Profited {} on {} activated/transacted for PvR of {}%'.format('%.0f' % (c.portfolio.portfolio_value - c.pvr['start']), '%.0f' % c.pvr['risk_hi'], '%.1f' % c.pvr['pvr']))  
        log.info('  QRet {} PvR {} CshLw {} MxLv {} RskHi {} Shrts {}'.format('%.2f' % q_rtrn, '%.2f' % c.pvr['pvr'], '%.0f' % c.pvr['cash_low'], '%.2f' % c.pvr['max_lvrg'], '%.0f' % c.pvr['risk_hi'], '%.0f' % shorts))

    def _minut():   # To preface each line with the minute of the day.  
        dt = get_datetime().astimezone(timezone('US/Eastern'))  
        minute = (dt.hour * 60) + dt.minute - 570  # (-570 = 9:31a)  
        return str(minute).rjust(3)

    date = get_datetime().date()  
    if c.pvr['date_prv'] != date: c.pvr['days'] += 1.0  
    do_summary = 0  
    if c.pvr['log_summary'] and c.pvr['days'] % c.pvr['log_summary'] == 0 and _minut() == '100':  
        do_summary = 1 # Log summary every x days  
    c.pvr['date_prv'] = date    # next line for speed  
    if c.pvr['cash'] == c.portfolio.cash and not do_summary and date != c.pvr['date_end']: return  
    c.pvr['cash'] = c.portfolio.cash

    longs         = 0                      # Longs  value  
    shorts        = 0                      # Shorts value  
    overshorts    = 0                      # Shorts value beyond longs plus cash  
    new_cash_low  = 0                      # To trigger logging in cash_low case  
    new_risk_hi   = 0  
    q_rtrn        = 100 * (c.portfolio.portfolio_value - c.pvr['start']) / c.pvr['start']  
    cash          = c.portfolio.cash  
    cash_dip      = int(max(0, c.pvr['start'] - cash))  
    if record_pvrp and cash < 0:    # Let negative cash ding less when portfolio is up.  
        cash_dip = int(max(0, c.pvr['start'] - cash * c.pvr['start'] / c.portfolio.portfolio_value))  
        # Imagine: Start with 10, grows to 1000, goes negative to -10, shud not be 200% risk.

    if int(cash) < c.pvr['cash_low']:                # New cash low  
        new_cash_low = 1  
        c.pvr['cash_low']   = int(cash)  
        if record_cash_low:  
            record(CashLow = int(c.pvr['cash_low'])) # Lowest cash level hit

    if record_max_lvrg:  
        if c.account.leverage > c.pvr['max_lvrg']:  
            c.pvr['max_lvrg'] = c.account.leverage  
            record(MaxLv = c.pvr['max_lvrg'])        # Maximum leverage  
            #log.info('Max Lvrg {}'.format('%.2f' % c.pvr['max_lvrg']))

    for p in c.portfolio.positions:  
        if not data.can_trade(p): continue  
        shrs = c.portfolio.positions[p].amount  
        if   shrs < 0: shorts += int(abs(shrs * data.current(p, 'price')))  
        elif shrs > 0: longs  += int(    shrs * data.current(p, 'price'))

    if shorts > longs + cash: overshorts = shorts             # Shorts when too high  
    if record_overshrt: record(OvrShrt = overshorts)          # Shorts beyond payable  
    if record_shorting: record(Shorts  = shorts)              # Shorts value as a positve  
    if record_leverage: record(Lvrg = c.account.leverage)     # Leverage  
    if record_cash:     record(Cash = int(cash))              # Cash

    risk = int(max(cash_dip,   shorts))  
    if record_risk: record(Risk = risk)       # Amount in play, maximum of shorts or cash used

    if risk > c.pvr['risk_hi']:  
        c.pvr['risk_hi'] = risk  
        new_risk_hi = 1  
        if record_risk_hi:  
            record(RiskHi = c.pvr['risk_hi']) # Highest risk overall

    if record_pnl:                            # "Profit and Loss" in dollars  
        record(PnL = min(0, c.pvr['cash_low']) + context.portfolio.pnl )

    if record_pvr or record_pvrp: # Profit_vs_Risk returns based on max amount actually spent (risk high)  
        if c.pvr['risk_hi'] != 0: # Avoid zero-divide  
            c.pvr['pvr'] = 100 * (c.portfolio.portfolio_value - c.pvr['start']) / c.pvr['risk_hi']  
            ptype = 'PvRp' if record_pvrp else 'PvR'  
            record(**{ptype: c.pvr['pvr']})

    if record_q_return:  
        record(QRet = q_rtrn)                 # Quantopian returns to compare to pvr returns curve

    if logging:  
        if new_risk_hi or new_cash_low:  
            qret    = ' QRet '   + '%.1f' % q_rtrn  
            lv      = ' Lv '     + '%.1f' % c.account.leverage if record_leverage else ''  
            pvr     = ' PvR '    + '%.1f' % c.pvr['pvr']       if record_pvr      else ''  
            pnl     = ' PnL '    + '%.0f' % c.portfolio.pnl    if record_pnl      else ''  
            csh     = ' Cash '   + '%.0f' % cash               if record_cash     else ''  
            shrt    = ' Shrt '   + '%.0f' % shorts             if record_shorting else ''  
            ovrshrt = ' Shrt '   + '%.0f' % overshorts         if record_overshrt else ''  
            risk    = ' Risk '   + '%.0f' % risk               if record_risk     else ''  
            mxlv    = ' MaxLv '  + '%.2f' % c.pvr['max_lvrg']  if record_max_lvrg else ''  
            csh_lw  = ' CshLw '  + '%.0f' % c.pvr['cash_low']  if record_cash_low else ''  
            rsk_hi  = ' RskHi '  + '%.0f' % c.pvr['risk_hi']   if record_risk_hi  else ''  
            log.info('{}{}{}{}{}{}{}{}{}{}{}{}'.format(_minut(), lv, mxlv, qret, pvr, pnl, csh, csh_lw, shrt, ovrshrt, risk, rsk_hi))  
    if do_summary: _pvr_(c)  
    if date == c.pvr['date_end']:        # Summary on last day once.  
        if 'pvr_summary_done' not in c: c.pvr_summary_done = 0  
        if not c.pvr_summary_done:  
            _pvr_(c)  
            elapsed = (time.time() - c.pvr['begin']) / 60  # minutes  
            log.info( '{}\nRuntime {} hr {} min'.format(c.pvr['run_str'],  
                int(elapsed / 60), '%.1f' % (elapsed % 60)))  
            c.pvr_summary_done = 1

def variance(x,*args):
    
    p = np.squeeze(np.asarray(args))
    Acov = np.cov(p.T)
    
    return np.dot(x,np.dot(Acov,x))

def jac_variance(x,*args):
    
    p = np.squeeze(np.asarray(args))
    Acov = np.cov(p.T)
        
    return 2*np.dot(Acov,x)
