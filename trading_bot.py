import time
import argparse
from xml.dom.domreg import well_known_implementations
from arbitrager import Arbitrager

WELCOME = """

Welcome to

     888 .d8888b.         888888b.   .d8888b. 888    
     888d88P  Y88b        888  "88b d88P  Y88b888    
     888888    888        888  .88P 888    888888    
 .d88888888    88888888b. 8888888K. 888    888888888 
d88" 888888    888888 "88b888  "Y88b888    888888    
888  888888    888888  888888    888888    888888    
Y88b 888Y88b  d88P888 d88P888   d88PY88b  d88PY88b.  
 "Y88888 "Y8888P" 88888P" 8888888P"  "Y8888P"  "Y888 
                  888                                
                  888                                
                  888

--A Dopex based arbitrage bot
ARBITRUM HACKATON 2022 - BOGOTA, COLOMBIA

#####################################################

"""

parser = argparse.ArgumentParser(
    prog="d0pb0t",
    description='Provide d0pb0t config data.'
)
parser.add_argument("--t", help="execute d0pb0t with test configuration", action="store_true")
parser.add_argument("--sil", help="execute d0pb0t in silent mode", action="store_true")
parser.add_argument("--TP", dest="TARGET_PROFIT", metavar="TARGET_PROFIT", help="define target profit", type=int)
parser.add_argument("--APR", dest="TARGET_APR", metavar="TARGET_APR", help="define target APR", type=int)
parser.add_argument("--slpT", dest="SLEEP_TIME", metavar="SLEEP_TIME", help="define sleep time", type=int)
parser.add_argument("--idx", dest="index", metavar="index", help="define index to be used", type=str)
parser.add_argument("--spot", dest="spot", help="define spot currency", type=str)
parser.add_argument("--w", dest="wallet", metavar="wallet", help="define wallet", type=str)
parser.add_argument("--slpP", dest="sleep_period", metavar="sleep_period", help="define sleep period", type=str)
parser.add_argument("--exp", dest="expiry", metavar="expiry", help="define expiry unix timestamp", type=int)
parser.add_argument("--siz", dest="order_sizes", metavar="order_sizes", help="define order sizes", type=int, nargs="+")
parser.add_argument("--trd", dest="trading", help="toggle on trading mode", action="store_true")

TARGET_PROFIT = -10
TARGET_APR = -100
SLEEP_TIME = 2 # 30
KEY_WORD = "-C"
TRADING = False

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

# objectif scrap data
config_eth = {
    "is_test": False,
    "index": "eth_usd",
    "spot": "ETH",
    "wallet": "0x",
    "sleep_period": 10,
    "expiry": 1666339200,
    "order_sizes": [1, 2, 5, 10],
}


agent = Arbitrager(config_eth)


def run_search():

    df = agent.get_arb_data()
    print(df)

    df.sort_values("APR", inplace=True)
    df_opp = df[df["APR"] >= TARGET_APR]
    apr_max = -1
    row_max = None

    if len(df_opp) > 0:

        for row in df_opp.iterrows():
            row = row[1]
            instrument = row["instrument_name"]

            if KEY_WORD in instrument:
                apr = row["APR"]
                print(f"Found opportunity for this week, searching {instrument}. apr: {apr}")

                try:
                    df_instrument = agent.search_instrument(instrument)
                    df_instrument.sort_values("APR", inplace=True)
                    print(df_instrument)

                    for row in df_instrument.iterrows():
                        row = row[1]

                        if row["PNL (USD)"] > TARGET_PROFIT:
                            order_size = row["Order Sizes"]

                            print(
                                f"instrument: {instrument}.. order_size: {order_size}. pnl: {round(row['PNL (USD)'],2)}. apr: {round(row['APR'],2)}"
                            )

                            if row["APR"] > apr_max:
                                row_max = row
                                apr_max = row["APR"]

                except:
                    print(f"Review search_instrument function, row: {row}")

        if TRADING and row_max:
            agent.do_trade(row["instrument_name"], row["Order Sizes"])

    return df


# running each half minute
def run_bot():

    print("start of the loop")
    i = 0

    while True:
        print(f"entering loop {i}...")

        try:
            run_search()
            i += 1

        except:
            try:
                agent.update()
                run_search()
                i += 1

            except Exception as e:
                i += 1

        time.sleep(SLEEP_TIME)
        
        if ((i%1) == 0):
            cont = input("Continue? [Y/N] ")

            while not (cont in ("Y", "N")):

                print("\nInvalid input. Please type Y for `yes` and N for `no`.\n\n")
                cont = input("Continue? [Y/N] ")

            if cont == "N":
                break


def main():

    args = parser.parse_args()
    
    if not args.sil:
        print(WELCOME)

    if args.t:
        Ellipsis

    if args.trading:
        TRADING = args.trading

    else:
        providedArgs = {
            k : v
            for k,v in args.__dict__.items()
            if not(v is None) and not(k in ("t", "sil", "trading"))
        }
        
        if "TARGET_PROFIT" in providedArgs.keys():
            TARGET_PROFIT = providedArgs["TARGET_PROFIT"]
            del providedArgs["TARGET_PROFIT"]
        
        if "TARGET_APR" in providedArgs.keys():
            TARGET_APR = providedArgs["TARGET_APR"]
            del providedArgs["TARGET_APR"]

        if "SLEEP_TIME" in providedArgs.keys():
            SLEEP_TIME = providedArgs["SLEEP_TIME"]
            del providedArgs["SLEEP_TIME"]
        
        config_eth.update(providedArgs)

    run_bot()

if __name__ == "__main__":
    main()

