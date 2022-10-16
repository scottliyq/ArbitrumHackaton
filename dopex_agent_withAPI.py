# deribit / dopex
# query prices of buy and sell on each part
# check if there is an arbitrage opportunity
import requests


class Dopex_agent():

    def __init__(self):
        self.BASE_URL = "https://api.dopex.io/api/v1"

    def get_SSOVs(self):

        response = requests.get(self.BASE_URL + "ssov")

        return response

    def get_SSOV_APYs(self, _asset):

        APYs_url = "/ssov/apy?asset={}".format(_asset)
        response = requests.get(self.BASE_URL + APYs_url)

        return response

    def get_SSOV_deposits(self, _asset, _type):

        if not (_type in ("CALL", "PUT")):
            raise Exception("Type provided is neither a CALL or a PUT")

        deposits_url = "/ssov/deposits?asset={}&type={}".format(_asset, _type)

        response = requests.get(self.BASE_URL + deposits_url)

        return response

    def get_SSOV_options_prices(self, _asset, _type):

        if not (_type in ("CALL", "PUT")):
            raise Exception("Type provided is neither a CALL or a PUT")

        options_prices_url = "/ssov/options/prices?asset={}&type={}".format(_asset, _type)

        response = requests.get(self.BASE_URL + options_prices_url)

        return response

# Main
if __name__ == "__main__":

    agent = Dopex_agent()

    response = agent.get_SSOV_deposits(
        "DPX", "CALL"
    )

    print("Status code: ", response.status_code)
    
    if response.status_code != 404:
        print(response.json())


        response = agent.get_SSOVs()

        print("Status code:", response.status_code)
        
        if response.status_code != 404:
            print(response.json())