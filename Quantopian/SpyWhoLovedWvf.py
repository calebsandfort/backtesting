import numpy as np
import scipy
import pandas as pd
from pytz import timezone
def initialize(context):
    #set_slippage(slippage.FixedSlippage(spread=0))
    
    context.bullish_stock = sid(37514) #UPRO
    context.bearish_stock = sid(38294) #TMF
    context.small_cap_stock = sid(37515) #TNA
    context.mid_cap_stock = sid(21507) #IJH
    context.vxx = sid(38054) #VXX -> Vix Bull
    context.xiv = sid(40516) #XIV -> VIX Bear
    
    context.spy = sid(38533) #UPRO
    context.shortSpy = sid(23921) #TLT -> Treasury                  EDV: 22887
    
    context.stocks = [context.bullish_stock,
                      context.bearish_stock,
                      context.small_cap_stock,
                      context.mid_cap_stock,
                      context.xiv]

    schedule_function(func = allocVOL, date_rule = date_rules.every_day(), time_rule = time_rules.market_open(minutes = 15))
   
    schedule_function(func = allocSPY, date_rule = date_rules.every_day(), time_rule = time_rules.market_close(minutes = 15))
    context.track_orders = 1    # toggle on|off
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
    context.portfolio_value_multiplier = 1.0
    context.spy_position_allocation = 0.0
    context.is_trading_day = False
    
    #schedule_function(queues,   date_rules.week_start(1), time_rules.market_open(minutes=60))
    schedule_function(set_is_trading_day,date_rules.every_day(),time_rules.market_open(minutes=60))
    schedule_function(allocate,date_rules.every_day(),time_rules.market_open(minutes=60))
    
    schedule_function(trade,date_rules.week_start(days_offset=1),time_rules.market_open(minutes=60))
    
    set_long_only()
    
    #Reporting
    context.stocks_pl = {}
    context.stocks_pl[context.bullish_stock] = 0.0
    context.stocks_pl[context.bearish_stock] = 0.0
    context.stocks_pl[context.small_cap_stock] = 0.0
    context.stocks_pl[context.mid_cap_stock] = 0.0
    context.stocks_pl[context.xiv] = 0.0
    context.stocks_pl[context.shortSpy] = 0.0
    
    schedule_function(record_leverage, date_rules.every_day())
    # schedule_function(final_reporting, date_rules.every_day())
   
def set_is_trading_day(context, data):
    context.is_trading_day = True

def record_leverage(context, data):
    record(leverage = context.account.leverage)
    record(mx_lvrg = context.mx_lvrg)
    context.mx_lvrg = 0
    context.is_trading_day = False
  
def final_reporting(context, data):
    if get_datetime().month == 1 and get_datetime().day == 25 and get_datetime().year == 2017:
        log.info("\n%s" % '\n'.join(["%s: $%.2f " % (x.symbol, context.stocks_pl[x]) for x in context.stocks_pl]))
    
def handle_data(context, data):  
    if 'mx_lvrg' not in context:             # Max leverage  
        context.mx_lvrg = 0                  # Init this instead in initialize() for better efficiency  
    if context.account.leverage > context.mx_lvrg:  
        context.mx_lvrg = context.account.leverage  
        record(mx_lvrg = context.mx_lvrg)

def place_order(context, data, stock, percent):
    # shares = get_shares(context, data, stock, percent)
    
    # if stock in context.portfolio.positions and shares == 0:
    #     pos = context.portfolio.positions[stock]
    #     context.stocks_pl[stock] += ((pos.amount * pos.last_sale_price) - (pos.amount * pos.cost_basis))
    
    order_target_percent(stock, percent)
    
def get_shares(context, data, stock, percent):
    current_price = data.current(stock, "price")
    shares = int((context.portfolio.portfolio_value * percent)/current_price)
    return shares
 
def get_holding_size(context, data, stock):
    if stock not in context.portfolio.positions:
        return 0.0
    
    pos = context.portfolio.positions[stock]
    
    return context.portfolio.portfolio_value / (pos.amount * pos.last_sale_price)
    
def allocate(context, data):
    context.run_count += 1
    prices = data.history(context.stocks, 'price', 17*390,'1m')
    ret = prices.pct_change()[1:].as_matrix(context.stocks)
    ret_mean = prices.pct_change().mean()
    ret_std = prices.pct_change().std()
    ret_norm = ret_mean/ret_std
    ret_norm = ret_norm.as_matrix(context.stocks)
#
#    alternate eps assignment method
#
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
                
            msg = "{0} runs, {1} SLSQP passes, {2} constraints passed".format(
                context.run_count, context.opt_pass_count,
                context.valid_constraint_count)
            #if(context.run_count>1000): log.info(msg)
        else:
            pass
            # log.info("constraint fail, SLSQP status = {0}".format(res.status))
    else:
        pass
        # log.info("SLSQP fail, SLSQP status = {0}".format(res.status))
    context.n += 1
    context.s += allocation
#
#---------- end of debugging code
def trade(context, data):
    if context.n > 0:
        allocation = context.s/context.n
    else:
        return
    
    context.n = 0
    context.s = np.zeros_like(context.stocks)
    context.x0 = allocation
    
    if get_open_orders():
        return
    
    for i,stock in enumerate(context.stocks):
        place_order(context, data, stock,allocation[i]*.7)
    # log.info (", ".join(["%s %0.3f" % (stock.symbol, allocation[i]) for i,stock in enumerate(context.stocks)]))
    # log.info("*************************************************************")
    # log.info("\n")

    
def allocVOL(context, data):    
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

    #Sell position when WVF crosses under 14
    if(WVF[-2] > WFV_limit and WVF[-1] <= WFV_limit):
        order_target_percent(xiv, 0.00) 

def allocSPY (context, data):  
    # if context.is_trading_day:
    #     return
    
    #spy_higher_then_Xdays_back
    if spy_change_logic(context, data, context.spy) :
        place_order(context, data, context.shortSpy,0)
        place_order(context, data, context.spy,(0.3))    
    else:
        short_size = get_holding_size(context, data, context.spy) + get_holding_size(context, data, context.bullish_stock) + (context.portfolio.cash/context.portfolio.portfolio_value)
        
        place_order(context, data, context.spy,0.0)
        # place_order(context, data, context.bullish_stock,0.0)
        place_order(context, data, context.shortSpy,0.3)
        
    # if context.small_cap_stock in context.portfolio.positions and not spy_change_logic(context, data, context.small_cap_stock):
    #     order_target_percent(context.small_cap_stock,0.0)
      
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

    spy_low = data.history(stock, "low", 2*period + 2, "1d")
    spy_high = data.history(stock, "high", 2*period + 2, "1d")
    spy_close = data.history(stock, "close", 2*period + 2, "1d")
    spy_prices = data.history(stock, "price", 2*period + 2, "1d")
    spy_lows = data.history(stock, "low", 2*period + 2, "1d")
    spy_highest = spy_prices.rolling(window = period).max()    
    
    spy_current = data.current(stock,"price")
    
    #Williams Vix Fix Formula
    wvf = ((spy_highest - spy_lows)/(spy_highest)) * 100
    sDev = mult * np.std(wvf[-bbl:])
    midLine = np.mean(wvf[-bbl:])
    lowerBand = midLine - sDev
    upperBand = midLine + sDev
    rangeHigh = (max(wvf[-lb:])) * ph

    spy_higher_then_Xdays_back = spy_close[-1] > spy_close[-Str]
    spy_lower_then_longterm = spy_close[-1] < spy_close[-ltLB]
    spy_lower_then_midterm = spy_close[-1] < spy_close[-mtLB]
    
    #Alerts Criteria
    alert2 = not (wvf[-1] >= upperBand and wvf[-1] >= rangeHigh) and (wvf[-2] >= upperBand and wvf[-2] >= rangeHigh)
    
    return (alert2 or spy_higher_then_Xdays_back) and (spy_lower_then_longterm or spy_lower_then_midterm)
    
def variance(x,*args):
    
    p = np.squeeze(np.asarray(args))
    Acov = np.cov(p.T)
    
    return np.dot(x,np.dot(Acov,x))

def jac_variance(x,*args):
    
    p = np.squeeze(np.asarray(args))
    Acov = np.cov(p.T)
        
    return 2*np.dot(Acov,x)
