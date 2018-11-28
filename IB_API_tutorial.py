# Gist example of IB wrapper ...
#
# Download API from http://interactivebrokers.github.io/#
#
# Install python API code /IBJts/source/pythonclient $ python3 setup.py install
#
# Note: The test cases, and the documentation refer to a python package called IBApi,
#    but the actual package is called ibapi. Go figure.
#
# Get the latest version of the gateway:
# https://www.interactivebrokers.com/en/?f=%2Fen%2Fcontrol%2Fsystemstandalone-ibGateway.php%3Fos%3Dunix
#    (for unix: windows and mac users please find your own version)
#
# Run the gateway
#
# user: edemo
# pwd: demo123
#
# Now I'll try and replicate the time telling example

from ibapi.wrapper import EWrapper
from ibapi.client import EClient
from ibapi.contract import Contract as IBcontract
from ibapi.order import Order
from ibapi.execution import ExecutionFilter
from threading import Thread
import queue
import datetime
import time
import pandas as pd
from pandas.tseries.offsets import BDay
import numpy as np
import math
from copy import deepcopy
from itertools import cycle

## This is the reqId IB API sends when a fill is received
FILL_CODE=-1

DEFAULT_MARKET_DATA_ID=50
DEFAULT_GET_CONTRACT_ID=43
DEFAULT_HISTORIC_DATA_ID=50
DEFAULT_EXEC_TICKER=78

## marker for when queue is finished
FINISHED = object()
STARTED = object()
TIME_OUT = object()

## marker to show a mergable object hasn't got any attributes
NO_ATTRIBUTES_SET=object()

ACCOUNT_UPDATE_FLAG = "update"
ACCOUNT_VALUE_FLAG = "value"
ACCOUNT_TIME_FLAG = "time"

class TestWrapper(EWrapper):
    """
    The wrapper deals with the action coming back from the IB gateway or TWS instance
    We override methods in EWrapper that will get called when this action happens, like currentTime
    Extra methods are added as we need to store the results in this object
    """
    def __init__(self):
        self._my_contract_details = {}
        self._my_historic_data_dict = {}
        self._my_requested_execution = {}
        self._my_market_data_dict = {}

        ## We set these up as we could get things coming along before we run an init
        self._my_executions_stream = queue.Queue()
        self._my_commission_stream = queue.Queue()
        self._my_open_orders = queue.Queue()
        
        ## use a dict as could have different accountids
        self._my_accounts = {}

        ## We set these up as we could get things coming along before we run an init
        self._my_positions = queue.Queue()
        self._my_errors = queue.Queue()

    ## error handling code
    def init_error(self):
        error_queue=queue.Queue()
        self._my_errors = error_queue

    def get_error(self, timeout=5):
        if self.is_error():
            try:
                return self._my_errors.get(timeout=timeout)
            except queue.Empty:
                return None

        return None

    def is_error(self):
        an_error_if=not self._my_errors.empty()
        return an_error_if

    def error(self, id, errorCode, errorString):
        ## Overriden method
        errormsg = "IB error id %d errorcode %d string %s" % (id, errorCode, errorString)
        self._my_errors.put(errormsg)
   
    ## Time telling code
    def init_time(self):
        time_queue=queue.Queue()
        self._time_queue = time_queue

        return time_queue

    def currentTime(self, time_from_server):
        ## Overriden method
        self._time_queue.put(time_from_server)

    ## get contract details code
    def init_contractdetails(self, reqId):
        contract_details_queue = self._my_contract_details[reqId] = queue.Queue()

        return contract_details_queue

    def contractDetails(self, reqId, contractDetails):
        ## overridden method

        if reqId not in self._my_contract_details.keys():
            self.init_contractdetails(reqId)

        self._my_contract_details[reqId].put(contractDetails)

    def contractDetailsEnd(self, reqId):
        ## overriden method
        if reqId not in self._my_contract_details.keys():
            self.init_contractdetails(reqId)

        self._my_contract_details[reqId].put(FINISHED)

    ## Historic data code
    def init_historicprices(self, tickerid):
        historic_data_queue = self._my_historic_data_dict[tickerid] = queue.Queue()

        return historic_data_queue

    def historicalData(self, tickerid , bar):

        ## Overriden method
        ## Note I'm choosing to ignore barCount, WAP and hasGaps but you could use them if you like
        bardata=(bar.date, bar.open, bar.high, bar.low, bar.close, bar.volume)

        historic_data_dict=self._my_historic_data_dict

        ## Add on to the current data
        if tickerid not in historic_data_dict.keys():
            self.init_historicprices(tickerid)

        historic_data_dict[tickerid].put(bardata)

    def historicalDataEnd(self, tickerid, start:str, end:str):
        ## overriden method

        if tickerid not in self._my_historic_data_dict.keys():
            self.init_historicprices(tickerid)

        self._my_historic_data_dict[tickerid].put(FINISHED)

    # market data
    def init_market_data(self, tickerid):
        market_data_queue = self._my_market_data_dict[tickerid] = queue.Queue()

        return market_data_queue

    def get_time_stamp(self):
        ## Time stamp to apply to market data
        ## We could also use IB server time
        return datetime.datetime.now()

    def tickPrice(self, tickerid , tickType, price, attrib):
        ##overriden method

        ## For simplicity I'm ignoring these but they could be useful to you...
        ## See the documentation http://interactivebrokers.github.io/tws-api/md_receive.html#gsc.tab=0
        # attrib.canAutoExecute
        # attrib.pastLimit

        this_tick_data=IBtick(self.get_time_stamp(),tickType, price)
        self._my_market_data_dict[tickerid].put(this_tick_data)
    
    def tickSize(self, tickerid, tickType, size):
        ## overriden method

        this_tick_data=IBtick(self.get_time_stamp(), tickType, size)
        self._my_market_data_dict[tickerid].put(this_tick_data)

    def tickString(self, tickerid, tickType, value):
        ## overriden method

        ## value is a string, make it a float, and then in the parent class will be resolved to int if size
        # Need to check if value can be converted to float first, otherwise the RaiseError disconnects from IB server
        if self.is_number(value):
            this_tick_data=IBtick(self.get_time_stamp(),tickType, float(value))
            self._my_market_data_dict[tickerid].put(this_tick_data)

    def tickGeneric(self, tickerid, tickType, value):
        ## overriden method

        this_tick_data=IBtick(self.get_time_stamp(),tickType, value)
        self._my_market_data_dict[tickerid].put(this_tick_data)

    # orders
    def init_open_orders(self):
        open_orders_queue = self._my_open_orders = queue.Queue()

        return open_orders_queue

    def orderStatus(self, orderId, status, filled, remaining, avgFillPrice, permid,
                    parentId, lastFillPrice, clientId, whyHeld, mktCapPrice):

        order_details = orderInformation(orderId, status=status, filled=filled,
                 avgFillPrice=avgFillPrice, permid=permid,
                 parentId=parentId, lastFillPrice=lastFillPrice, clientId=clientId,
                                         whyHeld=whyHeld, mktCapPrice=mktCapPrice)

        self._my_open_orders.put(order_details)

    def openOrder(self, orderId, contract, order, orderstate):
        """
        Tells us about any orders we are working now
        overriden method
        """

        order_details = orderInformation(orderId, contract=contract, order=order, orderstate = orderstate)
        self._my_open_orders.put(order_details)

    def openOrderEnd(self):
        """
        Finished getting open orders
        Overriden method
        """

        self._my_open_orders.put(FINISHED)

    """ Executions and commissions
    requested executions get dropped into single queue: self._my_requested_execution[reqId]
    Those that arrive as orders are completed without a relevant reqId go into self._my_executions_stream
    All commissions go into self._my_commission_stream (could be requested or not)
    The *_stream queues are permanent, and init when the TestWrapper instance is created
    """
    def init_requested_execution_data(self, reqId):
        execution_queue = self._my_requested_execution[reqId] = queue.Queue()

        return execution_queue

    def access_commission_stream(self):
        ## Access to the 'permanent' queue for commissions

        return self._my_commission_stream

    def access_executions_stream(self):
        ## Access to the 'permanent' queue for executions

        return self._my_executions_stream

    def commissionReport(self, commreport):
        """
        This is called if
        a) we have submitted an order and a fill has come back
        b) We have asked for recent fills to be given to us
        However no reqid is ever passed
        overriden method
        :param commreport:
        :return:
        """

        commdata = execInformation(commreport.execId, Commission=commreport.commission,
                        commission_currency = commreport.currency,
                        realisedpnl = commreport.realizedPNL)


        ## there are some other things in commreport you could add
        ## make sure you add them to the .attributes() field of the execInformation class

        ## These always go into the 'stream' as could be from a request, or a fill thats just happened
        self._my_commission_stream.put(commdata)

    def execDetails(self, reqId, contract, execution):
        """
        This is called if
        a) we have submitted an order and a fill has come back (in which case reqId will be FILL_CODE)
        b) We have asked for recent fills to be given to us (reqId will be
        See API docs for more details
        """
        ## overriden method

        execdata = execInformation(execution.execId, contract=contract,
                                   ClientId=execution.clientId, OrderId=execution.orderId,
                                   time=execution.time, AvgPrice=execution.avgPrice,
                                   AcctNumber=execution.acctNumber, Shares=execution.shares,
                                   Price = execution.price)

        ## there are some other things in execution you could add
        ## make sure you add them to the .attributes() field of the execInformation class

        reqId = int(reqId)

        ## We eithier put this into a stream if its just happened, or store it for a specific request
        if reqId==FILL_CODE:
            self._my_executions_stream.put(execdata)
        else:
            self._my_requested_execution[reqId].put(execdata)

    def execDetailsEnd(self, reqId):
        """
        No more orders to look at if execution details requested
        """
        self._my_requested_execution[reqId].put(FINISHED)

    ## order ids
    def init_nextvalidid(self):

        orderid_queue = self._my_orderid_data = queue.Queue()

        return orderid_queue

    def nextValidId(self, orderId):
        """
        Give the next valid order id
        Note this doesn't 'burn' the ID; if you call again without executing the next ID will be the same
        If you're executing through multiple clients you are probably better off having an explicit counter
        """
        if getattr(self, '_my_orderid_data', None) is None:
            ## getting an ID which we haven't asked for
            ## this happens, IB server just sends this along occassionally
            self.init_nextvalidid()

        self._my_orderid_data.put(orderId)

    ## get positions code
    def init_positions(self):
        positions_queue = self._my_positions = queue.Queue()

        return positions_queue

    def position(self, account, contract, position,
                 avgCost):

        ## uses a simple tuple, but you could do other, fancier, things here
        position_object = (account, contract, position,
                 avgCost)

        self._my_positions.put(position_object)

    def positionEnd(self):
        ## overriden method

        self._my_positions.put(FINISHED)

    ## get accounting data
    def init_accounts(self, accountName):
        accounting_queue = self._my_accounts[accountName] = queue.Queue()

        return accounting_queue

    def updateAccountValue(self, key:str, val:str, currency:str,
                            accountName:str):

        ## use this to seperate out different account data
        data = identifed_as(ACCOUNT_VALUE_FLAG, (key,val, currency))
        self._my_accounts[accountName].put(data)

    def updatePortfolio(self, contract, position:float,
                        marketPrice:float, marketValue:float,
                        averageCost:float, unrealizedPNL:float,
                        realizedPNL:float, accountName:str):

        ## use this to seperate out different account data
        data = identifed_as(ACCOUNT_UPDATE_FLAG, (contract, position, marketPrice, marketValue, averageCost,
                                          unrealizedPNL, realizedPNL))
        self._my_accounts[accountName].put(data)

    def updateAccountTime(self, timeStamp:str):

        #TODO: Not sure why this method was not recognizing accountName variable, where in RobCarver's example it is. Manually inputting here for now, but will cause issues if doing this for another account.
        accountName = 'U9509931'

        ## use this to seperate out different account data
        data = identifed_as(ACCOUNT_TIME_FLAG, timeStamp)
        self._my_accounts[accountName].put(data)

    def accountDownloadEnd(self, accountName:str):

        self._my_accounts[accountName].put(FINISHED)
    
    def is_number(self, s):
        try:
            float(s)
            return True
        except ValueError:
            return False
    
class TestClient(EClient):
    """
    The client method
    We don't override native methods, but instead call them from our own wrappers
    """
    def __init__(self, wrapper):
        
        ## Set up with a wrapper inside
        EClient.__init__(self, wrapper)

        self._market_data_q_dict = {}
        self._commissions=list_of_execInformation()

        ## We use these to store accounting data
        self._account_cache = simpleCache(max_staleness_seconds = 5*60)
        
        ## override function
        self._account_cache.update_data = self._update_accounting_data
    
    def speaking_clock(self):
            """
            Basic example to tell the time

            :return: unix time, as an int
            """

            print("Getting the time from the server... ")

            ## Make a place to store the time we're going to return
            ## This is a queue
            time_storage=self.wrapper.init_time()

            ## This is the native method in EClient, asks the server to send us the time please
            self.reqCurrentTime()

            ## Try and get a valid time
            MAX_WAIT_SECONDS = 5

            try:
                current_time = time_storage.get(timeout=MAX_WAIT_SECONDS)
            except queue.Empty:
                print("Exceeded maximum wait for wrapper to respond")
                current_time = None

            while self.wrapper.is_error():
                print(self.get_error())

            return current_time

    def resolve_ib_contract(self, ibcontract, reqId=DEFAULT_GET_CONTRACT_ID):

        """
        From a partially formed contract, returns a fully fledged version
        :returns fully resolved IB contract
        """

        ## Make a place to store the data we're going to return
        contract_details_queue = finishableQueue(self.init_contractdetails(reqId))

        print("Getting full contract details from the server... ")

        self.reqContractDetails(reqId, ibcontract)

        ## Run until we get a valid contract(s) or get bored waiting
        MAX_WAIT_SECONDS = 20
        new_contract_details = contract_details_queue.get(timeout = MAX_WAIT_SECONDS)

        while self.wrapper.is_error():
            print(self.get_error())

        if contract_details_queue.timed_out():
            print("Exceeded maximum wait for wrapper to confirm finished - seems to be normal behaviour")

        if len(new_contract_details)==0:
            print("Failed to get additional contract details: returning unresolved contract")
            return ibcontract

        if len(new_contract_details)>1:
            print("got multiple contracts using first one")

        new_contract_details=new_contract_details[0]

        resolved_ibcontract=new_contract_details.contract

        return resolved_ibcontract

    def get_IB_historical_data(self, ibcontract, durationStr="1 Y", barSizeSetting="1 day",
                               tickerid=DEFAULT_HISTORIC_DATA_ID):

        """
        Returns historical prices for a contract, up to today
        ibcontract is a Contract
        :returns list of prices in 4 tuples: Open high low close volume
        """

        ## Make a place to store the data we're going to return
        historic_data_queue = finishableQueue(self.init_historicprices(tickerid))

        # Request some historical data. Native method in EClient
        self.reqHistoricalData(
            tickerid,  # tickerId,
            ibcontract,  # contract,
            datetime.datetime.today().strftime("%Y%m%d %H:%M:%S %Z"),  # endDateTime,
            durationStr,  # durationStr,
            barSizeSetting,  # barSizeSetting,
            "TRADES",  # whatToShow,
            1,  # useRTH,
            1,  # formatDate
            False,  # KeepUpToDate <<==== added for api 9.73.2
            [] ## chartoptions not used
        )

        ## Wait until we get a completed data, an error, or get bored waiting
        MAX_WAIT_SECONDS = 20
        print("Getting historical data from the server... could take %d seconds to complete " % MAX_WAIT_SECONDS)

        historic_data = historic_data_queue.get(timeout = MAX_WAIT_SECONDS)

        while self.wrapper.is_error():
            print(self.get_error())

        if historic_data_queue.timed_out():
            print("Exceeded maximum wait for wrapper to confirm finished - seems to be normal behaviour")

        self.cancelHistoricalData(tickerid)


        return historic_data
    
    def start_getting_IB_market_data(self, resolved_ibcontract, tickerid=DEFAULT_MARKET_DATA_ID):
        """
        Kick off market data streaming
        :param resolved_ibcontract: a Contract object
        :param tickerid: the identifier for the request
        :return: tickerid
        """

        self._market_data_q_dict[tickerid] = self.wrapper.init_market_data(tickerid)
        self.reqMktData(tickerid, resolved_ibcontract, "", False, False, [])

        return tickerid

    def stop_getting_IB_market_data(self, tickerid):
        """
        Stops the stream of market data and returns all the data we've had since we last asked for it
        :param tickerid: identifier for the request
        :return: market data
        """

        ## native EClient method
        self.cancelMktData(tickerid)

        ## Sometimes a lag whilst this happens, this prevents 'orphan' ticks appearing
        time.sleep(5)

        market_data = self.get_IB_market_data(tickerid)

        ## output ay errors
        while self.wrapper.is_error():
            print(self.get_error())

        return market_data

    def get_IB_market_data(self, tickerid):
        """
        Takes all the market data we have received so far out of the stack, and clear the stack
        :param tickerid: identifier for the request
        :return: market data
        """

        ## how long to wait for next item
        MAX_WAIT_MARKETDATEITEM = 5
        market_data_q = self._market_data_q_dict[tickerid]

        market_data=[]
        finished=False

        while not finished:
            try:
                market_data.append(market_data_q.get(timeout=MAX_WAIT_MARKETDATEITEM))
            except queue.Empty:
                ## no more data
                finished=True

        return stream_of_ticks(market_data)


    def get_next_brokerorderid(self):
        """
        Get next broker order id
        :return: broker order id, int; or TIME_OUT if unavailable
        """

        ## Make a place to store the data we're going to return
        orderid_q = self.init_nextvalidid()

        self.reqIds(-1) # -1 is irrelevant apparently (see IB API docs)

        ## Run until we get a valid contract(s) or get bored waiting
        MAX_WAIT_SECONDS = 10
        try:
            brokerorderid = orderid_q.get(timeout=MAX_WAIT_SECONDS)
        except queue.Empty:
            print("Wrapper timeout waiting for broker orderid")
            brokerorderid = TIME_OUT

        while self.wrapper.is_error():
            print(self.get_error(timeout=MAX_WAIT_SECONDS))

        return brokerorderid

    def place_new_IB_order(self, ibcontract, order, orderid=None):
        """
        Places an order
        Returns brokerorderid
        """

        ## We can eithier supply our own ID or ask IB to give us the next valid one
        if orderid is None:
            orderid = self.get_next_brokerorderid()

            if orderid is TIME_OUT:
                raise Exception("I couldn't get an orderid from IB, and you didn't provide an orderid")

        print("Using order id of %d" % orderid)

        ## Note: It's possible if you have multiple traidng instances for orderids to be submitted out of sequence
        ##   in which case IB will break

        # Place the order
        self.placeOrder(
            orderid,  # orderId,
            ibcontract,  # contract,
            order  # order
        )

        return orderid

    def any_open_orders(self):
        """
        Simple wrapper to tell us if we have any open orders
        """

        return len(self.get_open_orders()) > 0

    def get_open_orders(self):
        """
        Returns a list of any open orders
        """

        ## store the orders somewhere
        open_orders_queue = finishableQueue(self.init_open_orders())

        ## You may prefer to use reqOpenOrders() which only retrieves orders for this client
        self.reqAllOpenOrders()

        ## Run until we get a terimination or get bored waiting
        MAX_WAIT_SECONDS = 5
        open_orders_list = list_of_orderInformation(open_orders_queue.get(timeout = MAX_WAIT_SECONDS))

        while self.wrapper.is_error():
            print(self.get_error())

        if open_orders_queue.timed_out():
            print("Exceeded maximum wait for wrapper to confirm finished whilst getting orders")

        ## open orders queue will be a jumble of order details, turn into a tidy dict with no duplicates
        open_orders_dict = open_orders_list.merged_dict()
        
        return open_orders_dict

    '''
    def get_open_orders_pd(self):

        order_attributes = ['contract','order','orderstate','status',
            'filled', 'avgFillPrice', 'permid',
            'parentId', 'lastFillPrice', 'clientId', 'whyHeld',
            'mktCapPrice']

        order_pd_list = []
        open_orders_dict = self.get_open_orders()
        for key, order in open_orders_dict.items():
            attributes = {}
            for attr in order_attributes:
                attributes[attr] = getattr(order, attr)
            order_pd_list.append(pd.DataFrame(attributes, index=[0]))
        open_orders_pd = pd.concat(order_pd_list, ignore_index=True)
        return open_orders_pd
    '''

    def get_open_orders_pd(self):

        open_orders_dict = self.get_open_orders()

        if open_orders_dict:
            a = []
            for key, value in open_orders_dict.items():
                a.append(value.__dict__)
            b = pd.DataFrame(a)

            c = []
            for i, row in b.iterrows():
                try:
                    c.append(row.contract.__dict__)
                except AttributeError:
                    print('Row {} could not be added\nRow: {}'.format(i, row))
            d = pd.DataFrame(c)

            e = pd.concat([b,d], axis=1)
            e.drop('contract', axis=1, inplace=True)

            f = []
            for i, row in e.iterrows():
                f.append(row.order.__dict__)
            g = pd.DataFrame(f)
            h = pd.concat([e,g], axis=1)
            h.drop('order', axis=1, inplace=True)

            # Join the time_added column to the open_orders DataFrame
            logged_orders = pd.read_pickle(self.pklAdd_orders)
            i = logged_orders.loc[:,['permId', 'time_added']]
            open_orders_pd = h.join(i.set_index('permId'), on='permId')
        else:
            open_orders_pd = pd.DataFrame(columns=[0])

        return open_orders_pd

    def get_executions_and_commissions(self, reqId=DEFAULT_EXEC_TICKER, execution_filter = ExecutionFilter()):
        """
        Returns a list of all executions done today with commission data
        """

        ## store somewhere
        execution_queue = finishableQueue(self.init_requested_execution_data(reqId))

        ## We can change ExecutionFilter to subset different orders
        ## note this will also pull in commissions but we would use get_executions_with_commissions
        self.reqExecutions(reqId, execution_filter)

        ## Run until we get a terimination or get bored waiting
        MAX_WAIT_SECONDS = 10
        exec_list = list_of_execInformation(execution_queue.get(timeout = MAX_WAIT_SECONDS))

        while self.wrapper.is_error():
            print(self.get_error())

        if execution_queue.timed_out():
            print("Exceeded maximum wait for wrapper to confirm finished whilst getting exec / commissions")

        ## Commissions will arrive seperately. We get all of them, but will only use those relevant for us
        commissions = self._all_commissions()

        ## glue them together, create a dict, remove duplicates
        all_data = exec_list.blended_dict(commissions)

        return all_data

    def _recent_fills(self):
        """
        Returns any fills since we last called recent_fills
        :return: list of executions as execInformation objects
        """

        ## we don't set up a queue but access the permanent one
        fill_queue = self.access_executions_stream()

        list_of_fills=list_of_execInformation()

        while not fill_queue.empty():
            MAX_WAIT_SECONDS = 5
            try:
                next_fill = fill_queue.get(timeout=MAX_WAIT_SECONDS)
                list_of_fills.append(next_fill)
            except queue.Empty:
                ## corner case where Q emptied since we last checked if empty at top of while loop
                pass

        ## note this could include duplicates and is a list
        return list_of_fills

    def recent_fills_and_commissions(self):
        """
        Return recent fills, with commissions added in
        :return: dict of execInformation objects, keys are execids
        """

        recent_fills = self._recent_fills()
        commissions = self._all_commissions() ## we want all commissions

        ## glue them together, create a dict, remove duplicates
        all_data = recent_fills.blended_dict(commissions)

        return all_data

    def _recent_commissions(self):
        """
        Returns any commissions that are in the queue since we last checked
        :return: list of commissions as execInformation objects
        """

        ## we don't set up a queue, as there is a permanent one
        comm_queue = self.access_commission_stream()

        list_of_comm=list_of_execInformation()

        while not comm_queue.empty():
            MAX_WAIT_SECONDS = 5
            try:
                next_comm = comm_queue.get(timeout=MAX_WAIT_SECONDS)
                list_of_comm.append(next_comm)
            except queue.Empty:
                ## corner case where Q emptied since we last checked if empty at top of while loop
                pass

        ## note this could include duplicates and is a list
        return list_of_comm

    def _all_commissions(self):
        """
        Returns all commissions since we created this instance
        :return: list of commissions as execInformation objects
        """

        original_commissions = self._commissions
        latest_commissions = self._recent_commissions()

        all_commissions = list_of_execInformation(original_commissions + latest_commissions)

        self._commissions = all_commissions

        # note this could include duplicates and is a list
        return all_commissions

    def cancel_order(self, orderid):

        ## Has to be an order placed by this client. I don't check this here -
        ## If you have multiple IDs then you you need to check this yourself.

        self.cancelOrder(orderid)

        ## Wait until order is cancelled
        start_time=datetime.datetime.now()
        MAX_WAIT_TIME_SECONDS = 10

        finished = False

        while not finished:
            if orderid not in self.get_open_orders():
                ## finally cancelled
                finished = True

            if (datetime.datetime.now() - start_time).seconds > MAX_WAIT_TIME_SECONDS:
                print("Wrapper didn't come back with confirmation that order was cancelled!")
                finished = True

        ## return nothing

    def cancel_all_orders(self):

        ## Cancels all orders, from all client ids.
        ## if you don't want to do this, then instead run .cancel_order over named IDs
        self.reqGlobalCancel()

        start_time=datetime.datetime.now()
        MAX_WAIT_TIME_SECONDS = 10

        finished = False

        while not finished:
            if not self.any_open_orders():
                ## all orders finally cancelled
                finished = True
            if (datetime.datetime.now() - start_time).seconds > MAX_WAIT_TIME_SECONDS:
                print("Wrapper didn't come back with confirmation that all orders were cancelled!")
                finished = True

        ## return nothing

    def get_current_positions(self):
        """
        Current positions held

        :return:
        Pandas dataframe of current positions
        """

        ## Make a place to store the data we're going to return
        positions_queue = finishableQueue(self.init_positions())

        ## ask for the data
        self.reqPositions()

        ## poll until we get a termination or die of boredom
        MAX_WAIT_SECONDS = 10
        positions_list = positions_queue.get(timeout=MAX_WAIT_SECONDS)

        while self.wrapper.is_error():
            print(self.get_error())

        if positions_queue.timed_out():
            print("Exceeded maximum wait for wrapper to confirm finished whilst getting positions")

        columns = ['account', 'contract', 'position', 'avg_cost']
        a = pd.DataFrame(positions_list, columns=columns)
        
        # Extract the Contract objects and save as a DataFrame
        b = []
        for value in a.loc[:, 'contract']:
            b.append(value.__dict__)
        c = pd.DataFrame(b)

        # Concat the Executions data with the Contract data
        d = pd.concat([a, c], axis=1)
        
        # Take out the Contract object column - it is now redundant
        e = d.drop(['contract'], axis=1)

        # Add column showing latest bought time of stock from executions pd
        executions = self.get_latest_executions()
        
        f = {}
        for i, symbol in e.symbol.items():

            if not symbol == 'USD':
                f[i] = self.get_latest_buy_time(symbol, executions)

        g = pd.Series(f, index=f.keys(), name='bought_datetime')
        positions_list_pd = pd.concat([e, g], axis=1)

        return positions_list_pd

    def _update_accounting_data(self, accountName):
        """
        Update the accounting data in the cache

        :param accountName: account we want to get data for
        :return: nothing
        """

        ## Make a place to store the data we're going to return
        accounting_queue = finishableQueue(self.init_accounts(accountName))

        ## ask for the data
        self.reqAccountUpdates(True, accountName)

        ## poll until we get a termination or die of boredom
        MAX_WAIT_SECONDS = 10
        accounting_list = accounting_queue.get(timeout=MAX_WAIT_SECONDS)

        while self.wrapper.is_error():
            print(self.get_error())

        if accounting_queue.timed_out():
            print("Exceeded maximum wait for wrapper to confirm finished whilst getting accounting data")

        # seperate things out, because this is one big queue of data with different things in it
        accounting_list = list_of_identified_items(accounting_list)
        seperated_accounting_data = accounting_list.seperate_into_dict()

        ## update the cache with different elements
        self._account_cache.update_cache(accountName, seperated_accounting_data)

        ## return nothing, information is accessed via get_... methods

    def get_accounting_time_from_server(self, accountName):
        """
        Get the accounting time from IB server

        :return: accounting time as served up by IB
        """

        #All these functions follow the same pattern: check if stale or missing, if not return cache, else update values

        return self._account_cache.get_updated_cache(accountName, ACCOUNT_TIME_FLAG)

    def get_accounting_values(self, accountName):
        """
        Get the accounting values from IB server

        :return: accounting values as served up by IB
        """

        #All these functions follow the same pattern: check if stale, if not return cache, else update values

        return self._account_cache.get_updated_cache(accountName, ACCOUNT_VALUE_FLAG)

    def get_accounting_updates(self, accountName):
        """
        Get the accounting updates from IB server

        :return: accounting updates as served up by IB
        """

        #All these functions follow the same pattern: check if stale, if not return cache, else update values

        return self._account_cache.get_updated_cache(accountName, ACCOUNT_UPDATE_FLAG)

class TestApp(TestWrapper, TestClient):
    def __init__(self, ipaddress, portid, clientid):
        TestWrapper.__init__(self)
        TestClient.__init__(self, wrapper=self)

        self.port = 7496
        self.ip = "127.0.0.1"
        self.clientID = 1
        self.buyFactor = .99
        self.SellFactor = 1.01
        self.rebalance_interval = 10
        self.maxBuyOrdersAtOnce = 30
        self.minInvSize = 1000
        self.stock_list = []
        self.maxCandidates=100
        self.leastPrice=3.00
        self.mostPrice=20.00
        self.fireSalePrice = self.leastPrice
        self.fireSaleAge = 6

        # Local file addresses
        self.csvAdd_stocks_to_trade = "/Users/chingaling/Documents/Algo Trading/BroCodePC/stocks_to_trade.csv"
        self.csvAdd_orders = "/Users/chingaling/Documents/Algo Trading/BroCodePC/orders.csv"
        self.csvAdd_exec = "/Users/chingaling/Documents/Algo Trading/BroCodePC/executions.csv"
        self.pklAdd_orders = "/Users/chingaling/Documents/Algo Trading/BroCodePC/orders.pkl"
        self.pklAdd_exec = "/Users/chingaling/Documents/Algo Trading/BroCodePC/executions.pkl"

        # Connect to IB API
        ipaddress = self.ip
        portid = self.port
        clientid = self.clientID

        self.connect(ipaddress, portid, clientid)
        self.init_error()
        thread = Thread(target = self.run)
        thread.start()

        setattr(self, "_thread", thread)
    
    def submit_order(self, resolved_ibcontract, action, shares, price, order_type, orderid, tif='GTC'):
        """
            Submits an order to IB API.

        Args:
            resolved_ibcontract: IBContract, must be fully resolved
            action: str, options: 'BUY', 'SELL'
            shares: int
            price: double
            order_type: str, options: 'MKT', 'LMT', etc.
            orderid: int, identifies which orderid to assign
            tif (optional): Time-in-force. Defaults to 'GTC'.

        Returns:
            Returns the orderid used for this order

        Raises:
            None
        """
        
        # Submit order instructions to IB server
        currOrder = Order()
        currOrder.action = action
        currOrder.orderType = order_type
        currOrder.totalQuantity = shares
        currOrder.lmtPrice = price
        currOrder.tif = tif
        currOrder.transmit = True
        currOrderId = self.place_new_IB_order(resolved_ibcontract, currOrder, orderid=orderid)
        print("Placed order, orderid is %d" % currOrderId)
        
        return currOrderId

    # Logging order entry
    def add_order_entry(self, orderid):
        
        '''
        Add a new log entry (somewhere, either CSV, cloud database, etc.) 
        keeping track of all order detail

        Returns: Nothing
        '''

        # Get open orders
        open_orders = self.get_open_orders_pd()
        
        if open_orders.id.isin([orderid]).any():
            order_pd_base = pd.read_pickle(self.pklAdd_orders)
            a = open_orders[open_orders.id == orderid]

            b = a.assign(time_added=datetime.datetime.now())
            order_pd = pd.concat([order_pd_base, b])
            order_pd.drop_duplicates(subset=['permid','conId'], inplace=True)
            order_pd.reset_index(drop=True, inplace=True)

            # Save latest stData to pickle file and csv locally
            order_pd.to_pickle(self.pklAdd_orders)
            order_pd.to_csv(self.csvAdd_orders)
        else:
            print("Orderid {} not in open_orders".format(orderid))

    def get_executions_and_commissions_pd(self):

        # Create DataFrame from get_executions_and_commissions method
        # Returns a pandas DataFrame of last 24 hours of executions. If none, returns empty DataFrame

        # Returns executions in the last 24 hours
        a = self.get_executions_and_commissions()

        # Check if any executions were returned
        if a:
            # Set it as a DataFrame, and move the index into the column
            b = pd.DataFrame.from_dict(a, orient='index')
            c = b.reset_index()

            # Extract the Execution objects and save as a DataFrame
            d = []
            for value in c.loc[:, 0]:
                d.append(value.__dict__)
            e = pd.DataFrame(d)

            # Extract the Contract objects and save as a DataFrame
            f = []
            for value in e.loc[:, 'contract']:
                f.append(value.__dict__)
            g = pd.DataFrame(f)

            # Concat the Executions data with the Contract data
            h = pd.concat([e, g], axis=1)
            
            # Take out the Contract object column - it is now redundant
            i = h.drop(['contract'], axis=1)

            # Convert time in to datettime object
            l = {}
            for j, row in i.iterrows():
                l[j] = datetime.datetime.strptime(row.time, '%Y%m%d  %H:%M:%S')
                l[j] = l[j].replace(tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
            k = pd.Series(l, index=l.keys(), name='dttime')

            executions_pd = pd.concat([i, k], axis=1)

            return executions_pd
        else:
            return pd.DataFrame(columns=[0])

    def get_latest_executions(self):
    
        # Loads the latest executions and returns the entire updated executions DataFrame
        # Saves the latest update to pickle file
        executions_pd_new = self.get_executions_and_commissions_pd()

        # Check if any new executions were received
        if not executions_pd_new.empty:
            executions_pd = pd.read_pickle(self.pklAdd_exec)
            a = pd.concat([executions_pd,executions_pd_new])
            b = a.drop_duplicates(subset=['id'], keep='last')
            updated_executions_pd = b.reset_index(drop=True)
            updated_executions_pd.to_pickle(self.pklAdd_exec)
            updated_executions_pd.to_csv(self.csvAdd_exec)
        else:
            updated_executions_pd = pd.read_pickle(self.pklAdd_exec)
        
        return updated_executions_pd

    def get_latest_buy_time(self, symbol, executions):
    
        # Retrieves the latest time that the symbol was bought.
        # Looks through the executions DataFrame for this info
        # Returns latest_buy_time as a dataframe object, or None if symbol == 'USD'
        
        if not symbol == 'USD':
            
            # Get the latest date for each symbol that it was bought (ClientId == 1)
            a = max(executions.loc[(executions.symbol == symbol) & (executions.ClientId == 1)].time)
            
            # Convert it to a datetime object
            latest_buy_time = datetime.datetime.strptime(a, '%Y%m%d  %H:%M:%S')
            
            return latest_buy_time
            
        return None

    def generate_stock_shortlist(self):

        # Return list of stocks to trade for the day
        self.stock_list = list(pd.read_csv(self.csvAdd_stocks_to_trade).Stocks)
        self.nextStock = cycle(self.stock_list)

    def create_resolved_ibcontract(self, stock_to_trade):
        # Create the contract object
        ibcontract = IBcontract()
        ibcontract.secType = "STK"
        ibcontract.symbol = stock_to_trade
        ibcontract.currency = "USD"
        resolved_ibcontract = self.resolve_ib_contract(ibcontract)
        print(resolved_ibcontract)

        # TODO: Investigate that we are getting the right stock out of all of the options
        return resolved_ibcontract
    
    def get_latest_price(self, resolved_ibcontract):
    
        # Get the last price
        tickerid = self.start_getting_IB_market_data(resolved_ibcontract)
        time.sleep(1)
        market_data1 = self.stop_getting_IB_market_data(tickerid)
        market_data1_as_df = market_data1.as_pdDataFrame()
        some_quotes = market_data1_as_df.resample("1S").last()[["last_trade_price"]]
        current_price = some_quotes.iloc[0][0]
        if np.isnan(current_price):
            print('Could not get latest_trade_price. Getting historical closing price')
            b = self.get_IB_historical_data(resolved_ibcontract, durationStr='1 D')
            if b:
                c = pd.DataFrame(b, columns=['date', 'open', 'high', 'low', 'close', 'volume'])
                current_price = c.close.loc[0]
            else:
                print('Did not receive historical data. Setting current_price as nan')
                current_price = np.nan
        
        print('Current price: {}'.format(current_price))
        return current_price
    
    def rebalance_sell_order(self, position_series):

        # Receive positions Series from output of get_current_positions()
        
        StockShares = position_series.position
        
        # We have to re-resolve the contract based on the quote. Some risk in not identifying the same security. For some reason the saved Contract object in our positions DataFrame does not square up exactly with their resolved contract.
        resolved_ibcontract = self.create_resolved_ibcontract(position_series.symbol)
        CurrPrice = self.get_latest_price(resolved_ibcontract)
        
        CostBasis = float(position_series.avg_cost)
        SellPrice = float(make_div_by_05(CostBasis*self.SellFactor, buy=False))
        
        stock = position_series.symbol
        today = datetime.datetime.now()
        
        # If we're past the fireSaleAge, and the CurrPrice is below the fireSalePrice or the CostBasis is higher than the CurrPrice, then place a sell order
        if (
            position_series.bought_datetime + BDay(self.fireSaleAge) < today 
            and (
                self.fireSalePrice>CurrPrice
                or CostBasis>CurrPrice
                )
            ):
            SellPrice = float(make_div_by_05(.95*CurrPrice, buy=False))
            print('Firesale')
            print("Selling {}, \tshares: {}, \tprice: {}".format(stock, StockShares, SellPrice))
            orderid = self.submit_order(resolved_ibcontract=resolved_ibcontract, action="SELL", shares=StockShares, price=SellPrice, order_type="LMT", orderid=None, tif="GTC")
            self.add_order_entry(orderid)
        else:
            print("Selling {}, \tshares: {}, \tprice: {}".format(stock, StockShares, SellPrice))
            orderid = self.submit_order(resolved_ibcontract=resolved_ibcontract, action="SELL", shares=StockShares, price=SellPrice, order_type="LMT", orderid=None, tif="GTC")
            self.add_order_entry(orderid)
        return orderid

    def rebalance_all_sell_orders(self):

        positions = self.get_current_positions()

        # Get list of open sell orders
        open_orders = self.get_open_orders_pd()
        if 'action' in open_orders.columns:
            open_sell_orders = open_orders[open_orders.action == 'SELL']
        else:
            open_sell_orders = pd.DataFrame(None, columns=[0])

        # Review if limit sell order exists for every position    
        for i, position in positions.iterrows():
            
            today = datetime.datetime.now()
            print('Considering placing sell order for {}'.format(position.symbol))

            # If the stock already has an existing limit sell order, continue to next stock. 
            #TODO: Check to make sure existing sell order is exact match (ie shares, limit price, what happens to updated limit price?, etc.)
            if 'symbol' in open_sell_orders.columns:
                if open_sell_orders.symbol.isin([position.symbol]).any():
                    print('Existing sell order in place. Skipping')
                    continue
            
            # If position in stock is 0, skip. Sometimes these will remain in our positions table for a day
            if position.position == 0:
                print('Do not have a position. Skipping')
                continue

            # If it's the USD position, skip it
            elif position.symbol == 'USD':
                print('USD is a cash position. Not for sale')
                pass
            
            # If the position is less than 2 days old, skip it
            #TODO: Need to double check the BDay logic holds given the timezone naive datetime objects. Since trading hours extend into midnight China time, this might affect the logic here.
            elif (position.bought_datetime + BDay(2) > today):
                print('Position held for less than 2 days. Skipping')
            
            else:
                orderid = self.rebalance_sell_order(position)

    def cancel_all_open_buy_orders(self, minutes=0):
    
        # Cancel all outstanding buy orders
        open_orders = self.get_open_orders_pd()
        if 'action' in open_orders.columns:
            open_orders = open_orders[open_orders.action == 'BUY']
            open_orders = open_orders[datetime.datetime.now() - open_orders.time_added > datetime.timedelta(minutes=minutes)]
            for _, order in open_orders.iterrows():
                if order.action == "BUY":
                    print("Cancelling this order: {}".format(order))
                    print(order.orderId)
                    self.cancel_order(order.orderId)
        else:
            print('open_orders did not have the action column, likely DataFrame is empty')

    def submit_buy_order(self, stock_to_trade):

        '''
        Submits a limit buy order, automatically calculating shares and price based on global parameters
        '''
        # TODO: Need to stop this round if the resolved_ibcontract could not be found.
        resolved_ibcontract = self.create_resolved_ibcontract(stock_to_trade)
        PH = self.get_IB_historical_data(resolved_ibcontract, durationStr='20 D')
        PH_df = pd.DataFrame(PH, columns=['date', 'open', 'high', 'low', 'close', 'volume'])
        PH_Avg = float(PH_df.close.mean())
        current_price = float(self.get_latest_price(resolved_ibcontract))
        
        # If can't retrieve current price, skip it for now
        if np.isnan(current_price):
            print('Could not get current price. Skipping for now') 
        else:
            
            # If there's a large 25% surge in price, buy it at current price
            if current_price > float(1.25*PH_Avg):
                buyPrice=float(current_price)
            else:
                buyPrice=float(current_price*self.buyFactor)
            buyPrice=float(make_div_by_05(buyPrice, buy=True))
            StockShares = int(self.minInvSize/buyPrice)
            print("Buying {}, \tshares: {}, \tprice: {}".format(stock_to_trade, StockShares, buyPrice))

            # Submit the buy order and log the order
            orderid = self.submit_order(resolved_ibcontract=resolved_ibcontract, action="BUY", shares=StockShares, price=buyPrice, order_type="LMT", orderid=None, tif="GTC")
            self.add_order_entry(orderid)

    def rebalance_buy_orders(self):
        
        '''
        Loops through a maximum of `maxBuyOrdersAtOnce` to buy new stock from our stock list
        Will need to initiate self.nextStock first with self.generate_stock_shortlist()

        Returns: Nothing
        '''
        
        # TODO: Keep getting errors when calling this function. Need to fix.
        #buying_power = self.get_buying_power()
        buying_power = 100000
        
        # Loops through for a max of maxBuyOrdersAtOnce
        # Will stop once buying_power is less than minInvSize
        for i in range(self.maxBuyOrdersAtOnce):
            print('{}\tBuying_power: {}'.format(i,buying_power))
            
            # If we don't have enough buying_power, stop buying
            if buying_power < self.minInvSize:
                print('buying_power ({}) less than minInvSize ({})'.format(buying_power, minInvSize))
                break
            
            # Get next stock to trade
            stock_to_trade = next(self.nextStock)
            print("Considering trading this stock: {}".format(stock_to_trade))

            # Get an update on our current situation to assess if we'll buy this stock
            positions = self.get_current_positions()
            open_orders = self.get_open_orders_pd()
            updated_executions_pd = self.get_latest_executions()
            todays_executions = updated_executions_pd[datetime.datetime.now(tz=datetime.timezone(datetime.timedelta(hours=8))) - updated_executions_pd.dttime < datetime.timedelta(days=1)]

            # Check if there is an existing buy order...
            #TODO: Check if this is actually a criteria in the Quantopian model
            cond1 = positions.symbol.isin([stock_to_trade]).any()
            
            # ...or if stock is already in portfolio
            cond2 = open_orders[open_orders.action == 'BUY'].symbol.isin([stock_to_trade]).any()
            
            # ...or if it was recently traded
            cond3 = todays_executions.symbol.isin([stock_to_trade]).any()
            
            # If any of the above 3 conditions are true, don't trade this stock
            if cond1 or cond2 or cond3:
                print('Wont trade this {}\nIn positions?: {}\tIn open_orders?: {}\tTraded today?: {}'.format(stock_to_trade, cond1, cond2, cond3))
            else:
                self.submit_buy_order(stock_to_trade)

            # Update our buying_power
            # TODO: Keep getting errors when calling this function. Need to fix.
            #buying_power = self.get_buying_power()

    def get_available_funds(self):
        '''
        Retrieves the amount of funds available to use for limit buy orders
        
        Returns: Float
        '''
        positions_list = self.get_current_positions()
        accountName = positions_list.account[0]
        accounting_values = self.get_accounting_values(accountName)
        a = pd.DataFrame(accounting_values, columns=['desc', 'amount', 'curr'])
        a.set_index(keys='desc', inplace=True)
        return float(a.loc['AvailableFunds-S'].amount)

    def get_total_buy_order_value(self):
        '''
        Retrieves current buy orders and calculates how much in value they add up to
        
        Return: float
        '''
        
        # TODO: Check with IB hotline if we can make more buy limit orders 
        # than our available funds allow for
        a = self.get_open_orders_pd()
        a = a[a.action == 'BUY']
        return sum(a.lmtPrice * a.totalQuantity)

    def get_buying_power(self):
        available_funds = self.get_available_funds()
        buy_order_value = self.get_total_buy_order_value()
        buying_power = available_funds - buy_order_value
        
        return buying_power

    def rebalance(self):
        
        '''
        Re-balancing method from 30_stock algo every 10 minutes. 
        Buy order cycles through list of 100 stock selected each day.
        '''

        # Close out all outstanding buy orders that were not fulfilled. Should be most of them
        self.cancel_all_open_buy_orders(minutes=0)

        # Create new sell orders as per algo strategy
        self.rebalance_all_sell_orders()

        # Submit new buy orders
        self.maxBuyOrdersAtOnce = 15
        self.rebalance_buy_orders()

    def main_trading(self):
        '''
        All of the code to run throughout the trading day
        '''

        #Before trading day starts, load up list of stock candidates
        self.stock_list = self.generate_stock_shortlist()

        # Start fresh and cancel all orders
        self.cancel_all_orders()

        # Calculate trading time
        trading_market_tz = datetime.timezone(-datetime.timedelta(hours=5))
        end_trading_day = datetime.time(hour=16, tzinfo=trading_market_tz)
        now = datetime.datetime.now()
        now = now.replace(tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
        end_trading_time = datetime.datetime.combine(now.date(), end_trading_day)
        while (now < end_trading_time):
            
            # In case there's a leftover connection, disconnect from that
            self.disconnect()

            # Connect to IB API
            self.__init__(self.ip, self.port, self.clientID)

            # Submit fresh buy and sell orders based on our algo rules
            self.rebalance()
            
            # After done rebalancing, disconnect and wait for `rebalance_interval`
            self.disconnect()

            # Wait for the rebalance_interval time (in minutes)
            time.sleep(self.rebalance_interval * 60)

            # Reset current time `now`
            now = datetime.datetime.now()
            now = now.replace(tzinfo=datetime.timezone(datetime.timedelta(hours=8)))
            
class finishableQueue(object):
    """
    Creates a queue which will finish at some point
    """
    def __init__(self, queue_to_finish):

        self._queue = queue_to_finish
        self.status = STARTED

    def get(self, timeout):
        """
        Returns a list of queue elements once timeout is finished, or a FINISHED flag is received in the queue

        :param timeout: how long to wait before giving up
        :return: list of queue elements
        """
        contents_of_queue=[]
        finished=False

        while not finished:
            try:
                current_element = self._queue.get(timeout=timeout)
                if current_element is FINISHED:
                    finished = True
                    self.status = FINISHED
                else:
                    contents_of_queue.append(current_element)
                    ## keep going and try and get more data

            except queue.Empty:
                ## If we hit a time out it's most probable we're not getting a finished element any time soon
                ## give up and return what we have
                finished = True
                self.status = TIME_OUT


        return contents_of_queue

    def timed_out(self):
        return self.status is TIME_OUT

def _nan_or_int(x):
    if not np.isnan(x):
        return int(x)
    else:
        return x

class stream_of_ticks(list):
    """
    Stream of ticks
    """

    def __init__(self, list_of_ticks):
        super().__init__(list_of_ticks)

    def as_pdDataFrame(self):

        if len(self)==0:
            ## no data; do a blank tick
            return tick(datetime.datetime.now()).as_pandas_row()

        pd_row_list=[tick.as_pandas_row() for tick in self]
        pd_data_frame=pd.concat(pd_row_list)

        return pd_data_frame

class tick(object):
    """
    Convenience method for storing ticks
    Not IB specific, use as abstract
    """
    def __init__(self, timestamp, bid_size=np.nan, bid_price=np.nan,
                 ask_size=np.nan, ask_price=np.nan,
                 last_trade_size=np.nan, last_trade_price=np.nan,
                 ignorable_tick_id=None):

        ## ignorable_tick_id keyword must match what is used in the IBtick class

        self.timestamp=timestamp
        self.bid_size=_nan_or_int(bid_size)
        self.bid_price=bid_price
        self.ask_size=_nan_or_int(ask_size)
        self.ask_price=ask_price
        self.last_trade_size=_nan_or_int(last_trade_size)
        self.last_trade_price=last_trade_price

    def __repr__(self):
        return self.as_pandas_row().__repr__()

    def as_pandas_row(self):
        """
        Tick as a pandas dataframe, single row, so we can concat together
        :return: pd.DataFrame
        """

        attributes=['bid_size','bid_price', 'ask_size', 'ask_price',
                    'last_trade_size', 'last_trade_price']

        self_as_dict=dict([(attr_name, getattr(self, attr_name)) for attr_name in attributes])

        return pd.DataFrame(self_as_dict, index=[self.timestamp])

class IBtick(tick):
    """
    Resolve IB tick categories
    """

    def __init__(self, timestamp, tickid, value):

        resolve_tickid=self.resolve_tickids(tickid)
        super().__init__(timestamp, **dict([(resolve_tickid, value)]))

    def resolve_tickids(self, tickid):

        tickid_dict=dict([("0", "bid_size"), ("1", "bid_price"), ("2", "ask_price"), ("3", "ask_size"),
                          ("4", "last_trade_price"), ("5", "last_trade_size")])

        if str(tickid) in tickid_dict.keys():
            return tickid_dict[str(tickid)]
        else:
            # This must be the same as the argument name in the parent class
            return "ignorable_tick_id"

"""
Mergable objects are used to capture order and execution information which comes from different sources and needs
  glueing together
"""

class mergableObject(object):
    """
    Generic object to make it easier to munge together incomplete information about orders and executions
    """

    def __init__(self, id, **kwargs):
        """
        :param id: master reference, has to be an immutable type
        :param kwargs: other attributes which will appear in list returned by attributes() method
        """

        self.id=id
        attr_to_use=self.attributes()

        for argname in kwargs:
            if argname in attr_to_use:
                setattr(self, argname, kwargs[argname])
            else:
                print("Ignoring argument passed %s: is this the right kind of object? If so, add to .attributes() method" % argname)

    def attributes(self):
        ## should return a list of str here
        ## eg return ["thingone", "thingtwo"]
        return NO_ATTRIBUTES_SET

    def _name(self):
        return "Generic Mergable object - "

    def __repr__(self):

        attr_list = self.attributes()
        if attr_list is NO_ATTRIBUTES_SET:
            return self._name()

        return self._name()+" ".join([ "%s: %s" % (attrname, str(getattr(self, attrname))) for attrname in attr_list
                                                  if getattr(self, attrname, None) is not None])

    def merge(self, details_to_merge, overwrite=True):
        """
        Merge two things
        self.id must match
        :param details_to_merge: thing to merge into current one
        :param overwrite: if True then overwrite current values, otherwise keep current values
        :return: merged thing
        """

        if self.id!=details_to_merge.id:
            raise Exception("Can't merge details with different IDS %d and %d!" % (self.id, details_to_merge.id))

        arg_list = self.attributes()
        if arg_list is NO_ATTRIBUTES_SET:
            ## self is a generic, empty, object.
            ## I can just replace it wholesale with the new object

            new_object = details_to_merge

            return new_object

        new_object = deepcopy(self)

        for argname in arg_list:
            my_arg_value = getattr(self, argname, None)
            new_arg_value = getattr(details_to_merge, argname, None)

            if new_arg_value is not None:
                ## have something to merge
                if my_arg_value is not None and not overwrite:
                    ## conflict with current value, don't want to overwrite, skip
                    pass
                else:
                    setattr(new_object, argname, new_arg_value)

        return new_object

class orderInformation(mergableObject):
    """
    Collect information about orders
    master ID will be the orderID
    eg you'd do order_details = orderInformation(orderID, contract=....)
    """

    def _name(self):
        return "Order - "

    def attributes(self):
        return ['contract','order','orderstate','status',
                 'filled', 'remaining', 'avgFillPrice', 'permid',
                 'parentId', 'lastFillPrice', 'clientId', 'whyHeld',
                'mktCapPrice']

class execInformation(mergableObject):
    """
    Collect information about executions
    master ID will be the execid
    eg you'd do exec_info = execInformation(execid, contract= ... )
    """

    def _name(self):
        return "Execution - "

    def attributes(self):
        return ['contract','ClientId','OrderId','time','AvgPrice','Price','AcctNumber',
                'Shares','Commission', 'commission_currency', 'realisedpnl']

class list_of_mergables(list):
    """
    A list of mergable objects, like execution details or order information
    """


    def merged_dict(self):
        """
        Merge and remove duplicates of a stack of mergable objects with unique ID
        Essentially creates the union of the objects in the stack
        :return: dict of mergableObjects, keynames .id
        """

        ## We create a new stack of order details which will contain merged order or execution details
        new_stack_dict = {}

        for stack_member in self:
            id = stack_member.id

            if id not in new_stack_dict.keys():
                ## not in new stack yet, create a 'blank' object
                ## Note this will have no attributes, so will be replaced when merged with a proper object
                new_stack_dict[id] = mergableObject(id)

            existing_stack_member = new_stack_dict[id]

            ## add on the new information by merging
            ## if this was an empty 'blank' object it will just be replaced with stack_member
            new_stack_dict[id] = existing_stack_member.merge(stack_member)

        return new_stack_dict


    def blended_dict(self, stack_to_merge):
        """
        Merges any objects in new_stack with the same ID as those in the original_stack
        :param self: list of mergableObject or inheritors thereof
        :param stack_to_merge: list of mergableObject or inheritors thereof
        :return: dict of mergableObjects, keynames .id
        """

        ## We create a new dict stack of order details which will contain merged details

        new_stack = {}

        ## convert the thing we're merging into a dictionary
        stack_to_merge_dict = stack_to_merge.merged_dict()

        for stack_member in self:
            id = stack_member.id
            new_stack[id] = deepcopy(stack_member)

            if id in stack_to_merge_dict.keys():
                ## add on the new information by merging without overwriting
                new_stack[id] = stack_member.merge(stack_to_merge_dict[id], overwrite=False)

        return new_stack

## Just to make the code more readable

class list_of_execInformation(list_of_mergables):
    pass

class list_of_orderInformation(list_of_mergables):
    pass

"""
Next section is 'scaffolding'

"""

class identifed_as(object):
    """
    Used to identify
    """

    def __init__(self, label, data):
        self.label = label
        self.data = data

    def __repr__(self):
        return "Identified as %s" % self.label

class list_of_identified_items(list):
    """
    A list of elements, each of class identified_as (or duck equivalent)

    Used to seperate out accounting data
    """
    def seperate_into_dict(self):
        """

        :return: dict, keys are labels, each element is a list of items matching label
        """

        all_labels = [element.label for element in self]
        dict_data = dict([
                             (label,
                              [element.data for element in self if element.label==label])
                          for label in all_labels])

        return dict_data

## cache used for accounting data
class simpleCache(object):
    """
    Cache is stored in _cache in nested dict, outer key is accountName, inner key is cache label
    """
    def __init__(self, max_staleness_seconds):
        self._cache = dict()
        self._cache_updated_local_time = dict()

        self._max_staleness_seconds = max_staleness_seconds

    def __repr__(self):
        return "Cache with labels"+",".join(self._cache.keys())

    def update_data(self, accountName):
        raise Exception("You need to set this method in an inherited class")

    def _get_last_updated_time(self, accountName, cache_label):
        if accountName not in self._cache_updated_local_time.keys():
            return None

        if cache_label not in self._cache_updated_local_time[accountName]:
            return None

        return self._cache_updated_local_time[accountName][cache_label]

    def _set_time_of_updated_cache(self, accountName, cache_label):
        # make sure we know when the cache was updated
        if accountName not in self._cache_updated_local_time.keys():
            self._cache_updated_local_time[accountName]={}

        self._cache_updated_local_time[accountName][cache_label] = time.time()

    def _is_data_stale(self, accountName, cache_label, ):
        """
        Check to see if the cached data has been updated recently for a given account and label, or if it's stale

        :return: bool
        """
        STALE = True
        NOT_STALE = False

        last_update = self._get_last_updated_time(accountName, cache_label)

        if last_update is None:
            ## we haven't got any data, so by construction our data is stale
            return STALE

        time_now = time.time()
        time_since_updated = time_now - last_update

        if time_since_updated > self._max_staleness_seconds:
            return STALE
        else:
            ## recently updated
            return NOT_STALE

    def _check_cache_empty(self, accountName, cache_label):
        """

        :param accountName: str
        :param cache_label: str
        :return: bool
        """
        CACHE_EMPTY = True
        CACHE_PRESENT = False

        cache = self._cache
        if accountName not in cache.keys():
            return CACHE_EMPTY

        cache_this_account = cache[accountName]
        if cache_label not in cache_this_account.keys():
            return CACHE_EMPTY

        return CACHE_PRESENT

    def _return_cache_values(self, accountName, cache_label):
        """

        :param accountName: str
        :param cache_label: str
        :return: None or cache contents
        """

        if self._check_cache_empty(accountName, cache_label):
            return None

        return self._cache[accountName][cache_label]

    def _create_cache_element(self, accountName, cache_label):

        cache = self._cache
        if accountName not in cache.keys():
            cache[accountName] = {}

        cache_this_account = cache[accountName]
        if cache_label not in cache_this_account.keys():
            cache[accountName][cache_label] = None

    def get_updated_cache(self, accountName, cache_label):
        """
        Checks for stale cache, updates if needed, returns up to date value

        :param accountName: str
        :param cache_label:  str
        :return: updated part of cache
        """

        if self._is_data_stale(accountName, cache_label) or self._check_cache_empty(accountName, cache_label):
            self.update_data(accountName)

        return self._return_cache_values(accountName, cache_label)

    def update_cache(self, accountName, dict_with_data):
        """

        :param accountName: str
        :param dict_with_data: dict, which has keynames with cache labels
        :return: nothing
        """

        all_labels = dict_with_data.keys()
        for cache_label in all_labels:
            self._create_cache_element(accountName, cache_label)
            self._cache[accountName][cache_label] = dict_with_data[cache_label]
            self._set_time_of_updated_cache(accountName, cache_label)

# Other random definitions
def make_div_by_05(s, buy=False):
    s *= 20.00
    s =  math.floor(s) if buy else math.ceil(s)
    s /= 20.00
    return s