import numpy as np
import scipy
import pandas as pd
from pytz import timezone
def initialize(context):
    
    context.stocks = [sid(32270),  #SSO -> S&P 2x
                      sid(38294),  #TMF -> Treasury 3x
                      sid(21508),  #IJR -> S&P Small-Cap
                      sid(21507),  #IJH -> S&P Mid-Cap
                      sid(40516)]  #XIV -> VIX Bear
    
    context.spy = sid(32270)       #SSO -> S&P 2x
    context.shortSpy = sid(23921)  #TLT -> Treasury                  EDV: 22887
                   
    context.vxx = sid(38054) #VXX -> Vix Bull
    context.xiv = sid(40516) #XIV -> VIX Bear
   
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
    #schedule_function(queues,   date_rules.week_start(1), time_rules.market_open(minutes=60))
    schedule_function(allocate,date_rules.every_day(),time_rules.market_open(minutes=60))
    
    schedule_function(trade,date_rules.week_start(days_offset=1),time_rules.market_open(minutes=60))
    
    set_long_only()
    
    schedule_function(record_leverage, date_rules.every_day())
   
def record_leverage(context, data):
    record(leverage = context.account.leverage)
    record(mx_lvrg = context.mx_lvrg)
    context.mx_lvrg = 0
                 
def handle_data(context, data):  
    if 'mx_lvrg' not in context:             # Max leverage  
        context.mx_lvrg = 0                  # Init this instead in initialize() for better efficiency  
    if context.account.leverage > context.mx_lvrg:  
        context.mx_lvrg = context.account.leverage  
        record(mx_lvrg = context.mx_lvrg)
    
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
            if(context.run_count>1000): log.info(msg)
        else:
            log.info("constraint fail, SLSQP status = {0}".format(res.status))
    else:
        log.info("SLSQP fail, SLSQP status = {0}".format(res.status))
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
        order_target_percent(stock,allocation[i]*.7)
    log.info (", ".join(["%s %0.3f" % (stock.symbol, allocation[i]) for i,stock in enumerate(context.stocks)]))
    log.info("*************************************************************")
    log.info("\n")

    
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
      

        #order_target_percent(safe_haven, 1.00)

def allocSPY (context, data):
    ####Inputs Tab Criteria.
    pd      = 28 #"LookBack Period Standard Deviation High")
    bbl     = 22 # "Bolinger Band Length")
    mult    = 1.05 # "Bollinger Band Standard Devaition Up")
    lb      = 22   # "Look Back Period Percentile High")
    ph      = .90# "Highest Percentile - 0.90=90%, 0.95=95%, 0.99=99%")

    #Criteria for Down Trend Definition for Filtered Pivots and Aggressive Filtered Pivots
    ltLB    = 40 # Long-Term Look Back Current Bar Has To Close Below This Value OR Medium Term--Default=40")
    mtLB    = 14 # Medium-Term Look Back Current Bar Has To Close Below This Value OR Long Term--Default=14")
    Str     = 3  # Entry Price Action Strength--Close > X Bars Back---Default=3")

    spy_low = data.history(context.spy, "low", 2*pd + 2, "1d")
    spy_high = data.history(context.spy, "high", 2*pd + 2, "1d")
    spy_close = data.history(context.spy, "close", 2*pd + 2, "1d")
    spy_prices = data.history(context.spy, "price", 2*pd + 2, "1d")
    spy_lows = data.history(context.spy, "low", 2*pd + 2, "1d")
    spy_highest = spy_prices.rolling(window = pd).max()    
    
    spy_current = data.current(context.spy,"price")
    
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


 
    #spy_higher_then_Xdays_back
    if (alert2 or spy_higher_then_Xdays_back) and (spy_lower_then_longterm or spy_lower_then_midterm) :
       
        order_target_percent(context.shortSpy,0)
        order_target_percent(context.spy,(0.3))
    
    else:
        order_target_percent(context.spy,0.0)
        order_target_percent(context.shortSpy,.3)
      

def variance(x,*args):
    
    p = np.squeeze(np.asarray(args))
    Acov = np.cov(p.T)
    
    return np.dot(x,np.dot(Acov,x))

def jac_variance(x,*args):
    
    p = np.squeeze(np.asarray(args))
    Acov = np.cov(p.T)
        
    return 2*np.dot(Acov,x)
