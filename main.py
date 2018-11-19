## Main python code for running algo on server

import sys
sys.path.insert(0, '/Users/chingaling/Documents/Algo Trading/BroCodePC')

import IB_API_tutorial as ib
import pandas as pd
import numpy as np
import time
import math
from itertools import cycle

#TODO: Start up main.py 30 min before trading starts at 9:30am EST Monday - Friday

class algoTrader(object):
    """
    This class provides all of the main tools to run the algorithm.
    It utilizes the wrapper code written by Rob Carver (first post here: https://qoppac.blogspot.com/2017/03/interactive-brokers-native-python-api.html)
    """
    def __init__(self):
        
        # Set some global variables
        self.BuyFactor = .99
        self.SellFactor = 1.01
        self.rebalance_interval = 10
        self.port = 4001
        self.maxStocksToHold = 30
        self.minInvSize = 2000
        self.stock_list = []

    def connect(self):
        self.app = ib.TestApp("127.0.0.1", self.port, 1)

    def main_trading():
        # Here goes all of the code to run throughout the trading day

        #Before trading day starts, load up list of stock candidates
        self.stock_list = generate_stock_shortlist()

        # Connect to the IB API
        app = ib.TestApp("127.0.0.1", port, 1)

        #TODO: Every rebalance_interval minutes, rebalance the portfolio
        while (current_time < end_trading_day):
            rebalance(BuyFactor=BuyFactor, SellFactor=SellFactor)
            time.wait(rebalance_interval * 60)

        # At the end of the day, disconnect from the IB API app
        app.disconnect()

    def rebalance(BuyFactor=.99, SellFactor=1.01):
        # Re-balancing method from 30_stock algo every 10 minutes. Buy order cycles through list of 100 stock selected each day.

        # Get outstanding buying power from account
        cash=get_buying_power()

        # Close out all outstanding buy orders that were not fulfilled. Should be most of them
        cancel_open_buy_orders()

        # Get list of current positions
        positions = get_current_positions()

        # Create new sell orders as per algo strategy
        rebalance_all_sell_orders()

        # Submit new buy orders
        rebalance_buy_orders()

    # Retrieve information from IB server
    def get_buying_power(self):
        #TODO: Retrieve remaining buying power from account

        pass

    def get_current_positions(self):
        #TODO: Retrieve list of current positions by stock symbol

        pass

    def get_open_sell_orders(self):
        #TODO: Retrieve list of all open sell orders:

        pass

    def get_stock_price(stock, method='bid'):
        #TODO: Retrieve stock current price

        pass

    def get_positions(self):
        #TODO: Retrieve current stock positions, save as pandas Dataframe

        positions = pd.Dataframe(0, columns=['stock', 'cost_basis', 'date_bought', 'time_bought', 'days_old'])
        return positions

    def generate_stock_shortlist(self):
        
        # Return list of stocks to trade for the day
        csvAddress = "/Users/chingaling/Documents/Algo Trading/BroCodePC/stocks_to_trade.csv"
        self.stock_list = list(pd.read_csv(csvAddress).Stocks)
        self.nextStock = cycle(stockNames)

    # Logging definitions
    def add_order_entry(orderid):
        #TODO: Add a new log entry (somewhere, either CSV, cloud database, etc.) keeping track of all order detail

        pass

    # Submitting orders
    def get_next_order_no():
        #TODO: Increment by 1 everytime we submit a new order. 


        pass

    def submit_order(stock, shares, price, order_type):

        # Submit order instructions to IB server
        currOrder = ib.Order()
        if shares > 0:
            currOrder.action="BUY"
        elif shares < 0:
            currOrder.action="SELL"
        else:
            print("Could not set currOrder.action. Shares variable is incorrect value or format.")
        currOrder.orderType = order_type
        currOrder.totalQuantity = shares
        currOrder.lmtPrice = price
        currOrder.tif = 'DAY'
        currOrder.transmit = True

        orderNo = get_next_order_no()

        order_dict[orderNo] = currOrder

        currOrderId = app.place_new_IB_order(resolved_ibcontract, currOrder, orderid=None)
        order_id_dict[orderNo] = currOrderId
        print("Placed limit order, orderid is %d" % currOrderId)



    def rebalance_sell_order(stock, positions, current_price_method):
        StockShares = positions[stock].amount
        CurrPrice = get_stock_price(stock, method=current_price_method)
        CostBasis = float(positions[stock].cost_basis)
        SellPrice = float(make_div_by_05(CostBasis*SellFactor, buy=False))
        
        if (stock in context.age and context.age[stock] == 1) :
            pass
        elif (
            stock in context.age 
            and context.MyFireSaleAge<=context.age[stock] 
            and (
                context.MyFireSalePrice>CurrPrice
                or CostBasis>CurrPrice
            )
        ):
            if (stock in context.age and context.age[stock] < 2) :
                pass
            elif stock not in context.age:
                context.age[stock] = 1
            else:
                SellPrice = float(make_div_by_05(.95*CurrPrice, buy=False))
                print("Selling {}, \tshares: {}, \tprice: {}".format(stock, StockShares, SellPrice))
                submit_order(stock, -StockShares, price=SellPrice, style="LMT")
        else:
            if (stock in context.age and context.age[stock] < 2) :
                pass
            elif stock not in context.age:
                context.age[stock] = 1
            else:
                print("Selling {}, \tshares: {}, \tprice: {}".format(stock, StockShares, SellPrice))
                orderid = submit_order(stock, -StockShares, style="limit")
                add_order_entry(orderid)

    def rebalance_all_sell_orders(current_price_method='bid'):

        positions = get_positions()

        # Get list of open sell orders
        open_sell_orders = get_open_sell_orders()

        # Review if limit sell order exists for every position    
        for stock in positions:

            # Check if stock has a existing limit sell order. If not, add one
            if not open_sell_orders(stock):
                rebalance_sell_order(stock=stock, positions=positions, current_price_method=current_price_method)

    def rebalance_buy_orders():
        WeightThisBuyOrder=float(1.00/context.maxStocksToHold)
        for ThisBuyOrder in range(context.MaxBuyOrdersAtOnce):
            stock = next(context.MyCandidate)
            PH = data.history([stock], 'price', 20, '1d')
            PH_Avg = float(PH.mean())
            CurrPrice = float(data.current([stock], 'price'))
            if np.isnan(CurrPrice):
                pass # probably best to wait until nan goes away
            else:
                if CurrPrice > float(1.25*PH_Avg):
                    BuyPrice=float(CurrPrice)
                else:
                    BuyPrice=float(CurrPrice*BuyFactor)
                BuyPrice=float(make_div_by_05(BuyPrice, buy=True))
                StockShares = int(WeightThisBuyOrder*cash/BuyPrice)
                #print("Buying {}, \tshares: {}, \tprice: {}".format(stock, StockShares, BuyPrice))
                order(stock, StockShares,
                    style=LimitOrder(BuyPrice)
                )

    def cancel_open_buy_orders():
        #TODO: Cancel all outstanding buy orders

        pass

def make_div_by_05(s, buy=False):
    s *= 20.00
    s =  math.floor(s) if buy else math.ceil(s)
    s /= 20.00
    return s
