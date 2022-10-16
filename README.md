# **`d0pB0t`**

```
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
```

`d0pB0t` is a `Dopex` based arbitrage bot.

## **Get started!**

The quickest way to test the bot is to clone this repository

```bash
git clone https://github.com/luksgrin/ArbitrumHackaton.git
cd ArbitrumHackaton
```

The next step is to execute one of the bots (either for Arbitrage with `Deribit` or `Lyra`)

```bash
python3 launch4Lyra.py
python3 launch4Deribit.py
```

This will launch `d0pbot` with the test configuration, and in "visualization mode" (i.e. it cannot trade for you).

## **Advanced**

`d0pb0t` allows for a series of flags to customize the settings. To see those flags, run

```bash
python3 launch4Lyra.py --help
python3 launch4Deribit.py --help
```

which will output

```
usage: d0pb0t [-h] [--t] [--sil] [--TP TARGET_PROFIT] [--APR TARGET_APR] [--slpT SLEEP_TIME] [--idx index] [--spot SPOT] [--w wallet] [--slpP sleep_period] [--exp expiry]
              [--siz order_sizes [order_sizes ...]] [--trd]

Provide d0pb0t config data.

optional arguments:
  -h, --help            show this help message and exit
  --t                   execute d0pb0t with test configuration
  --sil                 execute d0pb0t in silent mode
  --TP TARGET_PROFIT    define target profit
  --APR TARGET_APR      define target APR
  --slpT SLEEP_TIME     define sleep time
  --idx index           define index to be used
  --spot SPOT           define spot currency
  --w wallet            define wallet
  --slpP sleep_period   define sleep period
  --exp expiry          define expiry unix timestamp
  --siz order_sizes [order_sizes ...]
                        define order sizes
  --trd                 toggle on trading mode
```

For `d0pb0t` to perform a trade for you, it is mandatory to provide the `-w` and `--trd` arguments. **Note** that you will have to add the provided wallet's private key into the `.env` file of this projects. See [`.env.example`](./.env.example).