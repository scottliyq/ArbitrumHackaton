import asyncio
import websockets
import aiohttp
import json
import os
import numpy as np
from dotenv import load_dotenv

load_dotenv()

config = {
    "is_test": False,
    "index": "eth_usd",
}


class Deribit_Agent:
    def __init__(self, config):
        is_test = config.get("is_test")
        if is_test:
            self.client_id = os.getenv("DERIBIT_CLIENT_ID_TEST")
            self.client_secret = os.getenv("DERIBIT_CLIENT_SECRET_TEST")
            self.url = "wss://test.deribit.com/ws/api/v2"
        else:
            self.client_id = os.getenv("DERIBIT_CLIENT_ID")
            self.client_secret = os.getenv("DERIBIT_CLIENT_SECRET")
            self.url = "wss://www.deribit.com/ws/api/v2"

        self.auth_creds = self._get_auth_creds()

        self.index = config.get("index")  # eth_usd
        self.currency = self.index.split("-")[0].upper()
        self.orderbook_depth = config.get("orderbook_depth", 100)
        self.exchange_fee = config.get("exchange_fee", 0.0003)
        self.settlement_fee = config.get("settlement_fee", 0.00015)

    @staticmethod
    def async_loop(api, message):
        return asyncio.get_event_loop().run_until_complete(api(message))

    async def public_api(self, msg):
        """
        Calls Deribit public API with msg
        """
        async with websockets.connect(self.url) as websocket:
            await websocket.send(msg)
            while websocket.open:
                response = await websocket.recv()
                return json.loads(response)

    async def private_api(self, msg):
        """
        Calls Deribit private API with msg, used for trading

        """
        async with websockets.connect(self.url) as websocket:
            await websocket.send(self.auth_creds)
            while websocket.open:
                response = await websocket.recv()
                await websocket.send(msg)
                response = await websocket.recv()
                break
            return json.loads(response)

    ##############################
    #####   Trading section   ####
    ##############################
    def market_order(self, instrument, amount, direction):
        """
        Makes a market order
        """

        if direction.lower() == "long":
            side = "buy"
        elif direction.lower() == "short":
            side = "sell"
        else:
            raise ValueError("direction must be long or short")

        method = f"private/{side}"
        params = {
            "instrument_name": instrument,
            "amount": amount,
            "type": "market",
        }
        msg = self._get_msg(method, params)
        response = self.async_loop(self.private_api, msg)

        return response

    def limit_order(self, instrument, amount, direction, price, post_only, reduce_only):
        """
        Makes a Limit order
        """

        if direction.lower() == "long":
            side = "buy"
        elif direction.lower() == "short":
            side = "sell"
        else:
            raise ValueError("direction must be long or short")

        method = f"private/{side}"
        params = {
            "instrument_name": instrument,
            "amount": amount,
            "type": "limit",
            "price": price,
            "post_only": post_only,
            "reduce_only": reduce_only,
        }
        msg = self._get_msg(method, params)
        response = self.async_loop(self.private_api, msg)
        return response

    ##############################
    #####   Pricing section   ####
    ##############################

    def get_index_price(self):
        """
        Output: index price e.g eth_usd
        """
        method = "public/get_index_price"
        params = {"index_name": self.index}
        msg = self._get_msg(method, params)
        response = self.async_loop(self.public_api, msg)
        index_price = response["result"]["index_price"]
        return index_price

    def get_mid(self, instrument_name):
        """
        Output: mid price of the instrument
        """
        method = "public/get_book_summary_by_instrument"
        params = {"instrument_name": instrument_name}
        msg = self._get_msg(method, params)
        response = self.async_loop(self.public_api, msg)
        mid_price_eth = response["result"][0]["mid_price"]
        index_price = 1  # self.get_index_price()
        mid_price = mid_price_eth * index_price
        return mid_price

    def get_pure_quotes(self, instrument_name, amounts, direction):
        """
        Quote: Prices of Buying/Selling `amount` contract of option with direction = long/short in USD
        """
        orderbook = self.get_orderbook(instrument_name)
        index_price = 1  # self.get_index_price()
        quotes = []
        if direction == "long":
            side = "asks"
        elif direction == "short":
            side = "bids"
        else:
            raise ValueError("direction must be long or short")

        for amount in amounts:
            price_and_fees = self._get_avg_price_and_fees(orderbook[side], amount)
            quote = self._get_pure_quote(price_and_fees, amount, index_price, direction)
            quotes.append(quote)
        return quotes

    def get_orderbook(self, instrument_name):
        """
        Output: orderbook of class instrument
        """
        method = "public/get_order_book"
        params = {"instrument_name": instrument_name, "depth": self.orderbook_depth}
        msg = self._get_msg(method, params)
        response = self.async_loop(self.public_api, msg)
        result = response["result"]
        return {"bids": result["bids"], "asks": result["asks"]}

    def get_trading_fee(self, option_price):
        """
        amount: number of options to trade in the underlying e.g 10ETH
                see `https://legacy.deribit.com/pages/information/fees`
        output: trading fee in the underyling
        """
        return min(self.exchange_fee, option_price * 0.125)

    def get_settlement_fee(self, option_price):
        """
        amount: number of options to trade in the underlying e.g 10ETH
                see `https://legacy.deribit.com/pages/information/fees`
        output: trading fee in the underyling
        """
        return min(self.settlement_fee, option_price * 0.125)

    @staticmethod
    def _get_pure_quote(price_and_fees, amount, index_price, direction):
        """
        Get pure quote from price, fees, amount, index_price, direction
        """
        if direction == "long":
            quote = (
                (price_and_fees["price"] + price_and_fees["trading_fee"] + price_and_fees["settlement_fee"])
                * index_price
                * amount
            )
        elif direction == "short":
            quote = (
                (price_and_fees["price"] - price_and_fees["trading_fee"] - price_and_fees["settlement_fee"])
                * index_price
                * amount
            )
        else:
            raise Exception("wrong direction")
        return quote

    def _get_avg_price_and_fees(self, orderbook_side, amount):
        """
        Output: avg buy/sell price of option in ETH and trading + settlement fee in ETH
        """
        if len(orderbook_side) == 0:
            return {
                "price": np.nan,
                "trading_fee": 0,
                "settlement_fee": 0,
            }
        seen_amount = 0
        total_paid = 0
        total_trading_fee = 0
        total_settlement_fee = 0
        for level in orderbook_side:
            price = level[0]
            size = level[1]
            trading_fee = self.get_trading_fee(price)
            settlement_fee = self.get_settlement_fee(price)
            if size + seen_amount >= amount:
                size_diff = amount - seen_amount
                seen_amount = amount
                total_paid += price * size_diff
                total_trading_fee += trading_fee * size_diff
                total_settlement_fee += settlement_fee * size_diff
                return {
                    "price": total_paid / amount,
                    "trading_fee": total_trading_fee / amount,
                    "settlement_fee": total_settlement_fee / amount,
                }
            else:
                seen_amount += size
                total_paid += size * price
                total_trading_fee += size * trading_fee
                total_settlement_fee += size * settlement_fee

        return {
            "price": np.nan,
            "trading_fee": 0,
            "settlement_fee": 0,
        }

    ##############################
    #####   Account section   ####
    ##############################
    def get_account_summary(self, currency, extended=True):
        method = "private/get_account_summary"
        params = {"currency": currency, "extended": extended}
        msg = self._get_msg(method, params)
        summary = self.async_loop(self.private_api, msg)
        return summary

    def get_position(self, instrument):
        method = "private/get_position"
        params = {"instrument_name": instrument}
        msg = self._get_msg(method, params)
        positions = self.async_loop(self.private_api, msg)
        return positions

    @staticmethod
    def _get_msg(method, params, id=0):
        """
        Helper: msg to call API with
        """
        msg = {"jsonrpc": "2.0", "method": method, "id": int(id), "params": params}
        return json.dumps(msg)

    def _get_auth_creds(self):
        method = "public/auth"
        params = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        return self._get_msg(method, params)


config = {
    "is_test": False,
    "index": "eth_usd",
}
# agent = Deribit_Agent(config)
# print(agent.get_account_summary("ETH", False))
