import os, sys, json, time
import requests
import numpy as np
from datetime import datetime
import web3
from web3 import Web3
from web3.middleware import geth_poa_middleware
from eth_abi import decode_abi
from dotenv import load_dotenv

load_dotenv()

MAX_UINT = int(web3.constants.MAX_INT, 16)
unit = 10**18
path = "/".join(sys.path[0].split("/")[:0])


with open(os.path.join(path, "constants/contract_addresses.json"), "r") as jsonFile:
    contract_addresses = json.load(jsonFile)
    jsonFile.close()

with open(os.path.join(path, "abis/lyraquoter_abi.json"), "r") as jsonFile:
    quoter_abi = json.load(jsonFile)
    jsonFile.close()

with open(os.path.join(path, "abis/optionmarket_abi.json"), "r") as jsonFile:
    optionmarket_abi = json.load(jsonFile)
    jsonFile.close()

with open(os.path.join(path, "abis/optionmarket_wrapper_abi.json"), "r") as jsonFile:
    optionmarket_wrapper_abi = json.load(jsonFile)
    jsonFile.close()

with open(os.path.join(path, "abis/multicall_abi.json"), "r") as jsonFile:
    multicall_abi = json.load(jsonFile)
    jsonFile.close()

with open(os.path.join(path, "abis/price_feed_abi.json"), "r") as jsonFile:
    price_feed_abi = json.load(jsonFile)
    jsonFile.close()

with open(os.path.join(path, "abis/greek_cache_abi.json"), "r") as jsonFile:
    greek_cache_abi = json.load(jsonFile)
    jsonFile.close()


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


class Lyra_Agent:
    def __init__(self, config):
        self.wallet = config.get("wallet")
        self.private_key = os.getenv("PRIVATE_KEY")
        self.spot = config.get("spot", "ETH")

        self.w3_op = Web3(Web3.HTTPProvider(os.getenv("OPTIMISM_RPC_URL")))
        self.w3_op.middleware_onion.inject(geth_poa_middleware, layer=0)
        self.endpoint = "https://api.thegraph.com/subgraphs/name/lyra-finance/mainnet"
        self.boards_query = """
                            query Boards {
                                boards(where: { isExpired: false }) {
                                    boardId,
                                    expiryTimestamp,
                                    market {
                                    name
                                    },
                                    strikes {
                                    strikePrice
                                    strikeId
                                    }
                                }
                                }
                            """

        # contracts
        self.multicall_op = self.w3_op.eth.contract(
            address=contract_addresses["optimism"]["multicall"]["address"], abi=multicall_abi
        )
        self.quoter = self.w3_op.eth.contract(
            address=contract_addresses["optimism"]["lyra_quoter"]["address"], abi=quoter_abi
        )
        self.greek_cache = self.w3_op.eth.contract(
            address=contract_addresses["optimism"]["greek_cache"]["address"], abi=greek_cache_abi
        )
        self.optionmarket = self.w3_op.eth.contract(
            address=contract_addresses["optimism"][f"optionmarket_{self.spot.lower()}"]["address"], abi=optionmarket_abi
        )
        self.optionmarket_wrapper = self.w3_op.eth.contract(
            address=contract_addresses["optimism"]["optionmarket_wrapper"]["address"], abi=optionmarket_wrapper_abi
        )
        self.price_feed = self.w3_op.eth.contract(
            address=contract_addresses["optimism"]["price_feed"]["address"], abi=price_feed_abi
        )

        # lyra quotes
        self.iterations = config.get("iterations", 4)
        self.long_call_option_type = config.get("long_call_option_type", 0)  # long call = 0
        self.long_put_option_type = config.get("long_put_option_type", 1)
        self.short_call_option_type = config.get(
            "short_call_option_type", 2
        )  # short call sETH = 2, short call sUSD = 3
        self.short_put_option_type = config.get("short_put_option_type", 4)
        self.liquidation_margin = config.get("liquidation_margin", 1.25)

        # setting up board etc
        try:
            self.option_boards = self.build_option_boards_from_query()
        except:
            self.live_boards = self.get_live_boards()
            self.option_boards = self.build_option_boards()

    def get_mid_lyra(self, strike_id):
        """
        Return Lyra mid for corresponding strike_id
        TODO: should be adjusted for fees
        """
        unit = 10**18
        calldatas = [
            self.quoter.functions.quote(
                self.optionmarket.address, strike_id, self.iterations, option_type, unit
            )._encode_transaction_data()
            for option_type in [0, 2]
        ]
        calls = [{"target": self.quoter.address, "callData": cd} for cd in calldatas]
        rets = self.multicall_op.functions.aggregate(calls).call()
        decoded_rets = [self.decode(x) for x in rets[1]]
        premiums = [x[0] / 1e18 for x in decoded_rets]
        mid = (sum(premiums)) / 2
        return mid

    def get_calls(self, strike_id, amounts, option_type):
        """
        Return batch calls for multicall for specific (strike_id, option_type)
        NOTE: First call to quert sUSD/USD price from Chainlink, rest of call to get Lyra quotes
        """
        amounts = [int(amount * 1e18) for amount in amounts]
        susd_calldata = self.price_feed.functions.latestRoundData()._encode_transaction_data()
        calldatas = [
            self.quoter.functions.quote(
                self.optionmarket.address, strike_id, self.iterations, option_type, amount
            )._encode_transaction_data()
            for amount in amounts
        ]

        calls = [{"target": self.price_feed.address, "callData": susd_calldata}] + [
            {"target": self.quoter.address, "callData": cd} for cd in calldatas
        ]
        return calls

    def get_lyra_quotes(self, strike_id, amounts, direction):
        """
        Return Lyra quotes for specific (strike_id, option_type)
        """
        if direction == "long_call":
            option_type = self.long_call_option_type
        elif direction == "long_put":
            option_type = self.long_put_option_type
        elif direction == "short_call":
            option_type = self.short_call_option_type
        elif direction == "short_put":
            option_type = self.short_put_option_type
        else:
            raise ValueError("direction must be long or short")

        calls = self.get_calls(strike_id, amounts, option_type)
        rets = self.multicall_op.functions.aggregate(calls).call()
        susd_price = self.decode_susd_price(rets[1][0])
        decoded_rets = [self.decode(x) for x in rets[1][1:]]
        premiums = [susd_price * x[0] / 1e18 for x in decoded_rets]
        return premiums

    def get_batch_calls(self, instruments, amount=1):
        """
        Return batch calls for multicall for instruments quotes for specific amount
        NOTE: First call to query sUSD/USD price from Chainlink
        NOTE: Rest of calls are organized like [buy_quote_1, sell_quote_1, buy_quote_2, sell_quote_2 ....., buy_quote_n, sell_quote_n]
        """
        amount = 10**18 * amount
        susd_calldata = self.price_feed.functions.latestRoundData()._encode_transaction_data()
        calldatas = []
        for instrument in instruments:
            option_type = "call" if instrument["instrument_name"].endswith("C") else "put"
            buy_option_type = 0 if option_type == "call" else 1
            sell_option_type = 2 if option_type == "call" else 4
            buy_calldata = self.quoter.functions.quote(
                self.optionmarket.address, instrument["strike_id"], self.iterations, buy_option_type, amount
            )._encode_transaction_data()
            sell_calldata = self.quoter.functions.quote(
                self.optionmarket.address, instrument["strike_id"], self.iterations, sell_option_type, amount
            )._encode_transaction_data()
            calldatas += [buy_calldata, sell_calldata]

        calls = [{"target": self.price_feed.address, "callData": susd_calldata}] + [
            {"target": self.quoter.address, "callData": cd} for cd in calldatas
        ]
        return calls

    def get_batch_quotes(self, instruments, amount=1):
        """
        Return quotes for instruments by appending `buy_quote_lyra` and `sell_quote_lyra` to the instruments dict
        """
        calls = self.get_batch_calls(instruments, amount)
        rets = self.multicall_op.functions.aggregate(calls).call()
        susd_price = self.decode_susd_price(rets[1][0])
        decoded_rets = [self.decode(x) for x in rets[1][1:]]
        premiums = [susd_price * x[0] / 1e18 for x in decoded_rets]
        j = 0
        for i in range(len(instruments)):
            instruments[i]["buy_quote_lyra"] = premiums[j]
            instruments[i]["sell_quote_lyra"] = premiums[j + 1]
            j += 2
        return instruments

    def get_lyra_quote(self, strike_id, amount, direction):
        """
        Return Lyra quote for specific strike_id, amount, direction
        """
        if direction == "long":
            option_type = self.long_option_type
        elif direction == "short":
            option_type = self.short_option_type
        else:
            raise ValueError("direction must be long or short")

        amount = int(amount * 1e18)
        quote = self.quoter.functions.quote(
            self.optionmarket.address, strike_id, self.iterations, option_type, amount
        ).call()

        premium = quote[0] / 1e18
        return premium

    def get_collaterals_calls(self, instruments, index_price, amount=1):
        amount = int(amount * 1e18)
        susd_calldata = self.price_feed.functions.latestRoundData()._encode_transaction_data()
        calldatas = []

        for instrument in instruments:
            instrument_name = instrument["instrument_name"]
            option = "call" if instrument_name.endswith("C") else "put"
            option_type = self._get_option_type(option, direction="short")
            strike = self.get_strike_from_name(instrument_name)
            strike = int(strike * 1e18)
            expiry = self.get_expiry_from_name(instrument_name)
            spot_price = (
                index_price * self.liquidation_margin if option == "call" else index_price / self.liquidation_margin
            )
            spot_price = int(spot_price * 1e18)
            calldata = self.greek_cache.functions.getMinCollateral(
                option_type, strike, expiry, spot_price, amount
            )._encode_transaction_data()
            calldatas.append(calldata)

        calls = [{"target": self.price_feed.address, "callData": susd_calldata}] + [
            {"target": self.greek_cache.address, "callData": cd} for cd in calldatas
        ]
        return calls

    def get_required_collaterals(self, instruments, index_price, amount=1):
        calls = self.get_collaterals_calls(instruments, index_price, amount)
        rets = self.multicall_op.functions.aggregate(calls).call()
        susd_price = self.decode_susd_price(rets[1][0])
        requiered_collaterals = [susd_price * int(x.hex(), 16) / 1e18 for x in rets[1][1:]]
        return requiered_collaterals

    def get_min_collateral(self, option, direction, strike, expiry, spot_price, amount):
        option_type = self._get_option_type(option, direction)
        strike = int(strike * 10**18)
        spot_price = int(spot_price * 10**18)
        amount = int(amount * 10**18)
        min_collateral = self.greek_cache.functions.getMinCollateral(
            option_type, strike, expiry, spot_price, amount
        ).call()
        return min_collateral / 1e18

    @staticmethod
    def _get_option_type(option, direction):
        assert option in ["call", "put"], "option must be call or put"
        assert direction in ["long", "short"], "direction must be long or short"
        if direction == "long":
            if option == "call":
                return 0
            else:
                return 1
        else:
            if option == "call":
                return 3
            else:
                return 4

    @staticmethod
    def decode(return_data):
        return decode_abi(["uint256", "uint256"], return_data)

    @staticmethod
    def decode_susd_price(return_data):
        return decode_abi(["uint80", "int256", "uint256", "uint256", "uint80"], return_data)[1] / 1e8

    def get_live_boards(self):
        """'
        Get live boards from Lyra
        """
        return sorted(self.optionmarket.functions.getLiveBoards().call())

    def build_option_boards(self):
        """
        Build option boards and adding Deribit naming standard
        """
        boards = self.live_boards
        option_boards = {}
        for board_id in boards:
            option_board = self.build_option_board(board_id)
            option_boards.update(option_board)
        return option_boards

    def build_option_board(self, board_id):
        """
        Build one option board
        """
        option_board = self.optionmarket.functions.getOptionBoard(board_id).call()
        expiry_timestamp = option_board[1]
        timestamp_key = self.get_timestamp_key(expiry_timestamp)
        strike_ids = option_board[-1]
        strikes = self.get_strikes(strike_ids)
        calls = [timestamp_key + str(strike) + "-C" for strike in strikes]
        puts = [timestamp_key + str(strike) + "-P" for strike in strikes]
        board = {
            timestamp_key: {
                "expiry_timestamp": expiry_timestamp,
                "strike_ids": strike_ids,
                "strikes": strikes,
                "calls": calls,
                "puts": puts,
            }
        }
        return board

    def build_option_boards_from_query(self):
        query_result = self.run_query(self.boards_query, self.endpoint)
        option_boards = {}
        data = query_result["data"]
        boards = data["boards"]
        for board in boards:
            if board["market"]["name"] == "s" + self.spot:
                board = self.build_option_board_from_query(board)
                option_boards.update(board)

        return option_boards

    def build_option_board_from_query(self, board):
        expiry_timestamp = board["expiryTimestamp"]
        timestamp_key = self.get_timestamp_key(expiry_timestamp)
        strike_ids = [int(strike["strikeId"]) for strike in board["strikes"]]
        strikes = [int(int(strike["strikePrice"]) / 1e18) for strike in board["strikes"]]
        calls = [timestamp_key + str(strike) + "-C" for strike in strikes]
        puts = [timestamp_key + str(strike) + "-P" for strike in strikes]
        board = {
            timestamp_key: {
                "expiry_timestamp": expiry_timestamp,
                "strike_ids": strike_ids,
                "strikes": strikes,
                "calls": calls,
                "puts": puts,
            }
        }
        return board

    # function to use requests.post to make an API call to the subgraph url
    def run_query(self, query, endpoint):

        # endpoint where you are making the request
        request = requests.post(endpoint, json={"query": query})
        if request.status_code == 200:
            return request.json()
        else:
            raise Exception("Query failed. return code is {}.      {}".format(request.status_code, query))

    #########################
    ######## Trading #######
    #########################

    def sell_call(self, instrument_name, order_size, required_collateral):
        strike_id = self.get_strike_id_from_name(instrument_name)
        amount = int(10**18 * order_size)
        trade_params = {
            "strikeId": strike_id,
            "positionId": 0,
            "iterations": self.iterations,
            "optionType": 2,
            "amount": amount,
            "setCollateralTo": required_collateral,
            "minTotalCost": 0,
            "maxTotalCost": MAX_UINT,
        }

        w3 = self.w3_op
        sell_tx = self.optionmarket.functions.openPostion(trade_params).buildTransaction(
            {
                "chainId": 10,  # arbitrum chain id
                "gasPrice": w3.eth.gas_price,
                "from": self.wallet,
                "nonce": w3.eth.getTransactionCount(self.wallet),
            }
        )
        signed_sell_tx = w3.eth.account.sign_transaction(sell_tx, private_key=self.private_key)
        sell_tx_hash = w3.eth.send_raw_transaction(signed_sell_tx.rawTransaction)
        print(f"transaction link: https://optimistic.etherscan.io/tx/{sell_tx_hash.hex()}")
        tx_receipt = w3.eth.wait_for_transaction_receipt(sell_tx_hash)
        return tx_receipt

    #########################
    ######## Utilities #######
    #########################
    def get_timestamp_key(self, timestamp):
        date = datetime.fromtimestamp(timestamp)
        year = str(date.year)
        month = str_month[date.month]
        day = str(date.day)
        return self.spot + "-" + day + month + year[-2:] + "-"

    def get_strikes(self, strike_ids):
        calldatas = [
            self.optionmarket.functions.getStrikeAndExpiry(strike_id)._encode_transaction_data()
            for strike_id in strike_ids
        ]
        calls = [{"target": self.optionmarket.address, "callData": cd} for cd in calldatas]
        rets = self.multicall_op.functions.aggregate(calls).call()
        decoded_rets = [self.decode(x) for x in rets[1]]
        strikes = [int(x[0] / 1e18) for x in decoded_rets]
        return strikes

    def get_susd_price(self):
        susd_price = (self.price_feed.functions.latestRoundData().call())[1]
        return susd_price / 1e8

    @staticmethod
    def get_strike_from_name(instrument_name):
        """
        e.g INPUT = "ETH-2SEP22-800-C" -> OUTPUT = 800
        """
        strike = int(instrument_name.split("-")[-2])
        return strike

    def get_strike_id_from_name(self, instrument_name):
        """
        e.g INPUT = "ETH-2SEP22-800-C" -> OUTPUT = Lyra strike id
        """
        spot_and_expiry = "-".join(instrument_name.split("-")[:-2]) + "-"
        strike = self.get_strike_from_name(instrument_name)
        option_board = self.option_boards[spot_and_expiry]
        strikes = option_board["strikes"]
        index = strikes.index(strike)
        strike_id = option_board["strike_ids"][index]
        return strike_id

    def get_expiry_from_name(self, instrument_name):
        spot_and_expiry = "-".join(instrument_name.split("-")[:-2]) + "-"
        option_board = self.option_boards[spot_and_expiry]
        return option_board["expiry_timestamp"]


config = {"wallet": "0x"}
agent = Lyra_Agent(config)

instruments = [
    {"instrument_name": "ETH-21OCT22-1300-C", "strike": 1300, "strike_id": 239, "strike_idx": 0},
    {"instrument_name": "ETH-21OCT22-1350-C", "strike": 1350, "strike_id": 250, "strike_idx": 1},
    {"instrument_name": "ETH-21OCT22-1450-C", "strike": 1450, "strike_id": 253, "strike_idx": 2},
    {"instrument_name": "ETH-21OCT22-1600-C", "strike": 1600, "strike_id": 242, "strike_idx": 3},
]
