import asyncio, websockets
from operator import index
from datetime import datetime, timedelta

import json
import time
import numpy as np
import pandas as pd
from lyra_agent import Lyra_Agent
from dopex_agent import Dopex_Agent


str_month = {
    1: "JAN",
    2: "FEB",
    3: "MAR",
    4: "APR",
    5: "MAY",
    6: "JUN",
    7: "JUL",
    8: "AUG",
    9: "SEP",
    10: "OCT",
    11: "NOV",
    12: "DEC",
}
month_to_int = {v: k for k, v in str_month.items()}
ONEYEAR = timedelta(days=365).total_seconds()


class Arbitrager(Lyra_Agent, Dopex_Agent):
    def __init__(self, config):
        Lyra_Agent.__init__(self, config)
        Dopex_Agent.__init__(self, config)

        # Main parameters
        self.order_sizes = config.get("order_sizes")
        self.gas_fees = config.get("gas_fees", 0.2)
        self.margin = config.get("margin", 1.25)
        self.expiry = config.get("expiry")
        self.orderbooks = []
        self.instruments = self.get_instruments()

    def get_instruments(self):
        """
        Search through Dopex and Deribit to get matching options
        """
        strikes = self.strikes
        potential_instruments = self.get_potential_instruments(strikes)
        n = len(potential_instruments)

        instruments = [
            {
                "instrument_name": instrument_name,
                "strike": self.get_strike_from_name(instrument_name),
                "strike_id": self.get_strike_id_from_name(instrument_name),
                "strike_idx": self.strike_to_idx[self.get_strike_from_name(instrument_name)],
            }
            for instrument_name in potential_instruments
        ]
        return instruments

    def update(self):
        """
        Updates Dopex available strikes and class instruments
        """
        self.strikes = self.get_live_strikes()
        self.option_boards = self.build_option_boards_from_query()
        self.instruments = self.get_instruments()

    def get_arb_data(self):
        """
        search for arbs in self.instruments and format data in a dataframe
        """
        # self.instruments: contain instruments available in dopex/deribit in deribit format
        n = len(self.instruments)
        index_price = self.get_eth_price()
        timestamp = int(datetime.now().timestamp())

        df_dict = {}
        df_dict["Expiry"] = n * [datetime.fromtimestamp(self.expiry)]
        df_dict["Strike Price"] = list(map(lambda idx: self.instruments[idx]["strike"], range(n)))
        df_dict["instrument_name"] = list(map(lambda idx: self.instruments[idx]["instrument_name"], range(n)))
        df_dict["Buy Prices (ETH)"] = self.get_call_prices(df_dict["Strike Price"], self.expiry)
        instrument_prices = self.get_batch_quotes(self.instruments)
        sellPrices = [instrument_price["sell_quote_lyra"] for instrument_price in instrument_prices]

        df_dict["Sell Prices (USD)"] = sellPrices

        df = pd.DataFrame(df_dict)

        df["Buy Prices (USD)"] = df["Buy Prices (ETH)"] * index_price

        df["PNL (USD)"] = df["Sell Prices (USD)"] - df["Buy Prices (USD)"]
        df["APR"] = df["PNL (USD)"] / (1.25 * df["Strike Price"]) * (ONEYEAR / (self.expiry - timestamp)) * 100

        df = df.round({"Buy Prices (USD)": 2, "Sell Prices (USD)": 2, "PNL (USD)": 2, "APR": 2})

        return df

    def search_instrument(self, instrument_name):
        """
        Search for arbs in an instrument
        """

        index_price = self.get_eth_price()
        timestamp = int(datetime.now().timestamp())

        strike = self.get_strike_from_name(instrument_name)

        df_dict = {"Order Sizes": self.order_sizes}

        df_dict["Buy Prices (ETH)"] = self.get_call_quotes(strike, self.expiry, self.order_sizes)

        strike_id = self.get_strike_id_from_name(instrument_name)
        sellPrices = self.get_lyra_quotes(strike_id, self.order_sizes, "short_call")
        df_dict["Sell Prices (USD)"] = sellPrices

        df = pd.DataFrame(df_dict)

        df["Buy Prices (USD)"] = df["Buy Prices (ETH)"] * index_price

        df["PNL (USD)"] = df["Sell Prices (USD)"] - df["Buy Prices (USD)"]
        df["APR"] = df["PNL (USD)"] / (1.25 * strike) * (ONEYEAR / (self.expiry - timestamp)) * 100
        df["APR"] = np.divide(df["APR"], self.order_sizes)
        df = df.round({"Buy Prices (USD)": 2, "Sell Prices (USD)": 2, "PNL (USD)": 2, "APR": 2})

        return df

    #######################
    #######  TRADING ######
    ######################
    def do_trade(self, instrument_name, order_size):
        # check balances
        # 1. weth balance
        strike = self.get_strike_from_name(instrument_name)
        dopex_price = self.get_call_price(strike, self.expiry)
        weth_balance = self.get_token_balance("weth")
        if weth_balance < dopex_price:
            raise Exception("Unsufficient weth balance")

        # 2. seth balance
        lyra_balance = self.get_token_balance("seth", "optimism")
        index_price = self.get_eth_price()
        required_collateral = self.get_required_collaterals([instrument_name], index_price, order_size)
        if lyra_balance < required_collateral:
            raise Exception("Unsufficient seth balance")
        # trade with dopex
        buy_receipt = self.buy_call(strike, order_size)
        if buy_receipt["status"] == 1:
            response = self.sell_call(instrument_name, order_size, required_collateral)
            if "result" in response.keys():
                print("Trade succesful")
            else:
                raise Exception("Trade failed in Deribit please review")
        else:
            raise Exception("Trade failed in Dopex please review")

    def get_required_collateral(self, strike, order_size):
        pass

    #######################
    #######  UTILS ########
    ######################
    async def call_api(self, msg):
        """
        Calls Deribit public API with msg, and update orderbooks
        """
        async with websockets.connect(self.url) as websocket:
            await websocket.send(msg)
            while websocket.open:
                response = json.loads(await websocket.recv())
                self.orderbooks.append(response)
                break

    def get_potential_instruments(self, strikes):
        """'
        Return all Dopex options in deribit format
        """
        potential_instrument = []
        ts_key = self.get_timestamp_key(self.expiry)
        for strike in strikes:
            potential_instrument.append(ts_key + str(strike) + "-C")
        return potential_instrument

    def update_instruments(self):
        """
        To update instruments to search for
        """
        self.live_boards = self.get_live_boards()
        self.option_boards = self.build_option_boards()
        self.orderbooks = []
        self.instruments = self.get_instruments()

    def compute_apr(self, quote, pnl, index_price, direction):
        instrument_name = quote["instrument_name"]
        if direction == "sell_lyra":
            required_collateral = quote["required_collateral"]
        else:
            strike = self.get_strike_from_name(instrument_name)
            option = "call" if instrument_name.endswith("C") else "put"
            if option == "call":
                required_collateral = max(index_price * self.liquidation_margin - strike, 0)
            else:
                required_collateral = max(strike - index_price / self.liquidation_margin, 0)

        expiry_timestamp = self.get_expiry_from_name(instrument_name)
        timedelta = expiry_timestamp - datetime.now().timestamp()
        seconds_in_year = 60 * 60 * 24 * 365.25
        apr = 100 * (pnl) / (required_collateral - pnl) * seconds_in_year / timedelta
        return round(apr, 2)


config_eth = {
    "is_test": False,
    "index": "eth_usd",
    "spot": "ETH",
    "wallet": "0x",
    "sleep_period": 10,
    "expiry": 1666339200,
    "order_sizes": [10, 25, 50, 100],
}


arbitrager = Arbitrager(config_eth)
# print(arbitrager.instruments)
df = arbitrager.get_arb_data()
df.drop(["Expiry", "Buy Prices (ETH)", "instrument_name"], axis=1, inplace=True)
# print(df)
# print(arbitrager.search_instrument("ETH-21OCT22-1300-C"))
