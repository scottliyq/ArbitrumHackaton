import os, sys, json
from datetime import datetime
import web3
from web3 import Web3
from web3.middleware import geth_poa_middleware
from dotenv import load_dotenv

load_dotenv()

MAX_UINT = int(web3.constants.MAX_INT, 16)
unit = 10**18
path = "/".join(sys.path[0].split("/")[:0])


with open(os.path.join(path, "constants/contract_addresses.json"), "r") as jsonFile:
    contract_addresses = json.load(jsonFile)
    jsonFile.close()

with open(os.path.join(path, "abis/ethweekly_abi.json"), "r") as jsonFile:
    ethweekly_abi = json.load(jsonFile)
    jsonFile.close()


with open(os.path.join(path, "abis/multicall_abi.json"), "r") as jsonFile:
    multicall_abi = json.load(jsonFile)
    jsonFile.close()


with open(os.path.join(path, "abis/erc20_abi.json"), "r") as jsonFile:
    erc20_abi = json.load(jsonFile)
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
month_to_int = {v: k for k, v in str_month.items()}


class Dopex_Agent:
    def __init__(self, config):
        self.wallet = config.get("wallet")
        self.private_key = os.getenv("PRIVATE_KEY")
        self.spot = config.get("spot", "ETH")

        self.w3 = Web3(Web3.HTTPProvider(os.getenv("ARBITRUM_RPC_URL")))
        self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)

        # contracts
        self.multicall = self.w3.eth.contract(
            address=contract_addresses["arbitrum"]["multicall"]["address"], abi=multicall_abi
        )
        self.ethweekly = self.w3.eth.contract(
            address=contract_addresses["arbitrum"]["ethweekly"]["address"], abi=ethweekly_abi
        )

        self.strikes = self.get_live_strikes()

    #########################
    ######## Quoting #######
    #########################

    def get_call_price(self, strike, expiry):
        """
        Return dopex call price for strike and expiry
        """
        strike = int(strike * 10**8)
        calldatas = [
            self.ethweekly.functions.calculatePremium(strike, 10**18, expiry)._encode_transaction_data(),
            self.ethweekly.functions.calculatePurchaseFees(strike, 10**18)._encode_transaction_data(),
        ]
        calls = [{"target": self.ethweekly.address, "callData": cd} for cd in calldatas]
        rets = self.multicall.functions.aggregate(calls).call()
        price = int(rets[1][0].hex(), 16)
        fee = int(rets[1][1].hex(), 16)
        final_price = (price + fee) / 1e18
        return final_price

    def get_call_prices(self, strikes, expiry):
        """
        Return dopex call prices for strikes and expiry
        """
        strikes = [int(strike * 10**8) for strike in strikes]
        calldatas = [
            self.ethweekly.functions.calculatePremium(strike, 10**18, expiry)._encode_transaction_data()
            for strike in strikes
        ] + [
            self.ethweekly.functions.calculatePurchaseFees(strike, 10**18)._encode_transaction_data()
            for strike in strikes
        ]

        calls = [{"target": self.ethweekly.address, "callData": cd} for cd in calldatas]
        rets = self.multicall.functions.aggregate(calls).call()[1]
        n = len(rets)
        prices = [int(price.hex(), 16) for price in rets[: n // 2]]
        fees = [int(fee.hex(), 16) for fee in rets[n // 2 :]]
        final_prices = [(price + fee) / 1e18 for (price, fee) in zip(prices, fees)]
        return final_prices

    def get_call_quote(self, strike, expiry, amount):
        """
        Return dopex quotes for specific (strike_id, expiry)
        """
        strike = int(strike * 10**8)
        amount = int(amount * 10**18)
        calldatas = [
            self.ethweekly.functions.calculatePremium(strike, amount, expiry)._encode_transaction_data(),
            self.ethweekly.functions.calculatePurchaseFees(strike, amount)._encode_transaction_data(),
        ]
        calls = [{"target": self.ethweekly.address, "callData": cd} for cd in calldatas]
        rets = self.multicall.functions.aggregate(calls).call()
        price = int(rets[1][0].hex(), 16)
        fee = int(rets[1][1].hex(), 16)
        final_price = (price + fee) / 1e18
        return final_price

    def get_call_quotes(self, strike, expiry, amounts):
        """
        Return dopex quotes for specific (strike_id, expiry)
        """
        strike = int(strike * 10**8)
        amounts = [int(amount * 10**18) for amount in amounts]
        calldatas = [
            self.ethweekly.functions.calculatePremium(strike, amount, expiry)._encode_transaction_data()
            for amount in amounts
        ] + [
            self.ethweekly.functions.calculatePurchaseFees(strike, amount)._encode_transaction_data()
            for amount in amounts
        ]

        calls = [{"target": self.ethweekly.address, "callData": cd} for cd in calldatas]
        rets = self.multicall.functions.aggregate(calls).call()[1]
        n = len(rets)
        prices = [int(price.hex(), 16) for price in rets[: n // 2]]
        fees = [int(fee.hex(), 16) for fee in rets[n // 2 :]]
        final_prices = [(price + fee) / 1e18 for (price, fee) in zip(prices, fees)]
        return final_prices

    def get_eth_price(self):
        return self.ethweekly.functions.getCollateralPrice().call() / 1e8

    #########################
    ######## Trading #######
    #########################

    def buy_call(self, strike, expiry, amount):
        strike_idx = self.strike_to_idx[strike]
        amount = int(10**18 * amount)
        w3 = self.w3
        buy_tx = self.ethweekly.functions.purchase(strike_idx, amount, self.wallet).buildTransaction(
            {
                "chainId": 42161,  # arbitrum chain id
                "gasPrice": w3.eth.gas_price,
                "from": self.wallet,
                "nonce": w3.eth.getTransactionCount(self.wallet),
            }
        )
        signed_buy_tx = w3.eth.account.sign_transaction(buy_tx, private_key=self.private_key)
        buy_tx_hash = w3.eth.send_raw_transaction(signed_buy_tx.rawTransaction)
        print(f"transaction link: https://arbiscan.io/tx/{buy_tx_hash.hex()}")
        tx_receipt = w3.eth.wait_for_transaction_receipt(buy_tx_hash)
        return tx_receipt

    #########################
    ######## Utilities #######
    #########################

    def get_token_balance(self, token, network="arbitrum"):
        network = network.lower()
        w3 = Web3(Web3.HTTPProvider(os.getenv(f"{network.upper()}_RPC_URL")))
        w3.middleware_onion.inject(geth_poa_middleware, layer=0)
        token_address = contract_addresses[network][token]["address"]
        token_contract = w3.eth.contract(address=token_address, abi=erc20_abi)
        decimals = contract_addresses[network][token]["decimals"]
        try:
            balance = token_contract.functions.balanceOf(self.wallet).call()
        except:
            try:
                balance = token_contract.functions.balanceOf(self.wallet).call()
            except:
                raise Exception(f"Failed to get {token} balance twice on {network}")
        return balance / 10**decimals

    def get_live_strikes(self):
        """'
        Get live boards from dopex
        """
        current_epoch = self.ethweekly.functions.currentEpoch().call()
        epoch_data = self.ethweekly.functions.getEpochData(current_epoch).call()
        strikes = epoch_data[7]
        strikes = [int(strike / 10**8) for strike in strikes]
        self.strike_to_idx = {}
        for i in range(len(strikes)):
            self.strike_to_idx[strikes[i]] = i
        return strikes

    def get_timestamp_key(self, timestamp):
        date = datetime.fromtimestamp(timestamp)
        year = str(date.year)
        month = str_month[date.month]
        day = str(date.day)
        return self.spot + "-" + day + month + year[-2:] + "-"

    @staticmethod
    def get_strike_from_name(instrument_name):
        """
        e.g INPUT = "ETH-2SEP22-800-C" -> OUTPUT = 800
        """
        strike = int(instrument_name.split("-")[-2])
        return strike

    @staticmethod
    def get_expiry_timestamp_from_name(instrument_name):
        """
        e.g INPUT = "ETH-2SEP22-800-C" -> OUTPUT = 800
        """
        date = instrument_name.split("-")[1]
        year = 2000 + int(date[-2:])
        month = month_to_int[date[-5:-2]]
        day = int(date[:-5])
        return int(datetime(year, month, day).timestamp())


config = {"wallet": "0x"}
# agent = Dopex_Agent(config)
# print(agent.get_call_quotes(1300, 1666339200, [10, 20]))
# print(agent.strikes)
# print(agent.strike_to_idx)
