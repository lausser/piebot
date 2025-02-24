import hashlib
import hmac
import json
import requests
import signal
import sys
from termcolor import colored as termcolor_colored
import time
import os

from _config import *

min_order_value = 0.25


# Stops PieBot gracefully
class StopSignal:
    stop_now = False

    def __init__(self):
        signal.signal(signal.SIGINT, self.exit_gracefully)
        signal.signal(signal.SIGTERM, self.exit_gracefully)

    def exit_gracefully(self, *args):
        self.stop_now = True
        print()
        print(colored("Shutting down...", "cyan"))
        print()


def colored(text, color):
    if not sys.stdin.isatty():
        return text
    else:
        return termcolor_colored(text, color)

# Prints the current time
def current_time(new_line):
    time_data = time.strftime("%H:%M:%S - %d/%m/%Y", time.localtime())
    if new_line:
        print(colored(time_data + ": ", "yellow"), end="")
    else:
        print(colored(time_data, "yellow"))


# Gets the total available value of the portfolio
def get_available_portfolio_value(value):
    # Keeps aside the defined USDT reserves
    usdt_reserve_value = (value / 100) * (usdt_reserve * 100)

    total_available_balance = value - usdt_reserve_value

    return total_available_balance


# Gets the total balance of a coin
def get_coin_balance(coin):
    coin_balance_request = {
        "id": 100,
        "method": "private/user-balance",
        "api_key": api_key,
        "params": {
            "currency": coin
        },
        "nonce": int(time.time() * 1000)
    }

    coin_balance_response = requests.post("https://api.crypto.com/exchange/v1/private/user-balance",
                                          headers={"Content-type": "application/json"},
                                          data=json.dumps(sign_request(req=coin_balance_request)))
    coin_balance_data = json.loads(coin_balance_response.content)
    if not coin_balance_data["result"]["data"]:
        coin_total_balance = 0
        error = True
    else:
        quantity = coin_balance_data["result"]["data"][0]["position_balances"][0]["quantity"]
        reserved_qty = coin_balance_data["result"]["data"][0]["position_balances"][0]["reserved_qty"]
        coin_total_balance = float(quantity) - float(reserved_qty)
        error = False

    return coin_total_balance, error


# Gets the price of a coin pair
def get_coin_price(pair):
    get_price_response = requests.get("https://api.crypto.com/exchange/v1/public/get-tickers?instrument_name=" + pair)
    error = False
    ticker = json.loads(get_price_response.content)
    if "message" in ticker and ticker["message"] == "Invalid instrument_name":
        return 0.0, True
    coin_price = ticker["result"]["data"][0]["b"]
    if coin_price == None:
        # there is no bid at this moment, take latest trade's price
        coin_price = ticker["result"]["data"][0]["a"]
    return float(coin_price), error


# Gets the details of a coin pair
def get_pair_details(pair):
    def get_instrument(instruments, name):
        for instrument in instruments:
            if instrument["symbol"] == name:
                return instrument

    response = requests.get("https://api.crypto.com/exchange/v1/public/get-instruments")
    data = json.loads(response.content)
    instruments = data["result"]["data"]

    details = get_instrument(instruments, pair)
    if details == None:
        # there is no HNT_USDT any more, try HNT_USD
        details = get_instrument(instruments, pair.replace("USDT", "USD"))

    return details


# Gets the total value of the portfolio
def get_portfolio_value(pairs, include_usdt):
    total_balance = 0

    for pair in pairs:
        # Gets the total number of coins for this coin pair
        coin_balance, balance_error = get_coin_balance(pair[0])

        # Gets the current price for this coin pair
        coin_price, price_error = get_coin_price(pair[1])

        total_balance = total_balance + (coin_balance * coin_price)

    if include_usdt:
        # Get the total balance of USDT and add it to the current collected balance
        usdt_total_balance, usdt_error = get_coin_balance("USDT")

        total_balance = total_balance + usdt_total_balance

    return total_balance


# Submits a buy order
def order_buy(pair, notional):
    # Finds the required price precision for this coin pair
    pair_data = get_pair_details(pair)
    price_precision = pair_data["quote_decimals"]

    # Converts the notional into a number with the correct number of decimal places
    notional = "%0.*f" % (price_precision, notional)

    order_buy_request = {
        "id": time.time_ns(),
        "method": "private/create-order",
        "api_key": api_key,
        "params": {
            "instrument_name": pair,
            "side": "BUY",
            "type": "MARKET",
            "notional": notional
        },
        "nonce": int(time.time() * 1000)
    }

    order_buy_response = requests.post("https://api.crypto.com/exchange/v1/private/create-order",
                                  headers={"Content-type": "application/json"},
                                  data=json.dumps(sign_request(req=order_buy_request)))

    return order_buy_response


# Submits a sell order
def order_sell(pair, quantity):
    # Finds the required quantity precision for this coin pair
    pair_data = get_pair_details(pair)
    quantity_precision = pair_data["quantity_decimals"]

    # Converts the quantity into a number with the correct number of decimal places
    quantity = "%0.*f" % (quantity_precision, quantity)

    order_sell_request = {
        "id": time.time_ns(),
        "method": "private/create-order",
        "api_key": api_key,
        "params": {
            "instrument_name": pair,
            "side": "SELL",
            "type": "MARKET",
            "quantity": quantity
        },
        "nonce": int(time.time() * 1000)
    }

    order_sell_response = requests.post("https://api.crypto.com/exchange/v1/private/create-order",
                                       headers={"Content-type": "application/json"},
                                       data=json.dumps(sign_request(req=order_sell_request)))

    return order_sell_response


# Checks everything is in order before the bot runs
def pre_flight_checks():
    print(colored("Performing pre-flight checks...", "cyan"))

    # Checks whether the environment has been defined
    try:
        environment
    except NameError:
        print(colored("Your environment is missing from the config file", "red"))
        sys.exit()

    # Checks whether the API key and API secret have been defined
    if "API_KEY" in os.environ:
        global api_key
        api_key = os.environ["API_KEY"]
    if "API_SECRET" in os.environ:
        global api_secret
        api_secret = os.environ["API_SECRET"]
    try:
        api_key and api_secret
    except NameError:
        print(colored("Your API key and API secret are missing from the config file", "red"))
        sys.exit()

    # Checks whether the trading pairs have been defined, and if there is enough to begin trading
    try:
        pair_list
    except NameError:
        print(colored("Your trading coin pairs are missing from the config file", "red"))
        sys.exit()
    else:
        if len(pair_list) < 1:
            print(colored("You need to use at least one coin pair", "red"))
            sys.exit()

    # Checks whether the Buy task frequency has been defined
    try:
        buy_frequency
    except NameError:
        print(colored("Your Buy task frequency is missing from the config file", "red"))
        sys.exit()
    else:
        if buy_frequency < 1:
            print(colored("Your Buy task frequency must be at least 1 hour", "red"))
            sys.exit()

    # Checks whether the Rebalance task frequency has been defined
    try:
        rebalance_frequency
    except NameError:
        print(colored("Your Rebalance task frequency is missing from the config file", "red"))
        sys.exit()
    else:
        if rebalance_frequency < 0:
            print(colored("Your Rebalance task frequency cannot be less than 0", "red"))
            sys.exit()

    # Checks whether the maximum Buy order value has been defined and is valid
    try:
        buy_order_value
    except NameError:
        print(colored("Your Buy order value is missing from the config file", "red"))
        sys.exit()
    else:
        if buy_order_value < min_order_value:
            print(colored("Your Buy order value cannot be smaller than the minimum order value", "red"))
            sys.exit()

    # Checks whether the USDT reserve amount has been defined
    try:
        usdt_reserve
    except NameError:
        print(colored("Your USDT reserve amount is missing from the config file", "red"))
        sys.exit()
    else:
        if usdt_reserve < 0:
            print(colored("You need to define a valid USDT reserve. If you don't want to use a reserve, set the value as 0", "red"))
            sys.exit()
        elif usdt_reserve > 80:
            print(colored("Your USDT reserve must be 80% or lower", "red"))
            sys.exit()

    # Send a private request to test if the API key and API secret are correct
    init_request = {
        "id": 100,
        "method": "private/get-account-summary",
        "api_key": api_key,
        "params": {
            "currency": "USDT"
        },
        "nonce": int(time.time() * 1000)
    }

    init_response = requests.post("https://api.crypto.com/v2/private/get-account-summary",
                                  headers={"Content-type": "application/json"},
                                  data=json.dumps(sign_request(req=init_request)))
    init_status = init_response.status_code

    if init_status == 200:
        # The bot can connect to the account, has been started, and is waiting to be called
        print(colored("Pre-flight checks successful", "green"))
        for position in get_account_details():
            print("{:<10s} {:20.4f} {:14.8f} = {:10.2f} {:s}".format(position["coin"], position["balance"], float(position["price"]), float(position["balance"]) * float(position["price"]), position["state"]))

    else:
        # Could not connect to the account
        print(colored("Could not connect to your account. Please ensure the API key and API secret are correct and have the right privileges", "red"))
        sys.exit()


def get_account_details():
    # return a list of positions with keys coin, balance, price each
    positions = []
    init_request = {
        "id": 100,
        "method": "private/get-account-summary",
        "api_key": api_key,
        "params": {
#            "currency": "USDT"
        },
        "nonce": int(time.time() * 1000)
    }

    init_response = requests.post("https://api.crypto.com/v2/private/get-account-summary",
                                  headers={"Content-type": "application/json"},
                                  data=json.dumps(sign_request(req=init_request)))
    init_status = init_response.status_code

    if init_status == 200:
        summary_data = init_response.json()
        ticker_request = {
            "id": 100,
            "method": "private/get-account-summary",
            "api_key": api_key,
            "params": {},
            "nonce": int(time.time() * 1000)
        }

        ticker_response = requests.get("https://api.crypto.com/v2/public/get-ticker",
                                  headers={"Content-type": "application/json"},
                                  data=json.dumps(sign_request(req=ticker_request)))
        ticker_status = ticker_response.status_code
        ticker_data = ticker_response.json()
        for account in sorted(summary_data["result"]["accounts"], key=lambda x: x["currency"]):
            if account["currency"] == "USDT":
                positions.append({
                    "account": account_name,
                    "coin": "USDT",
                    "balance": account["balance"],
                    "price": 1,
                    "state": "unmanaged",
                })
            elif account["balance"] > 0.0:
                pair = account["currency"]+"_USDT"
                latest_bid = [tick["a"] for tick in ticker_data["result"]["data"] if tick["i"] == pair]
                if latest_bid:
                    positions.append({
                        "account": account_name,
                        "coin": account["currency"],
                        "balance": account["balance"],
                        "price": latest_bid[0],
                        "state": "managed" if [p for p in pair_list if p[0] == account["currency"]] else "unmanaged",
                    })
        return positions


# Signs private requests
def sign_request(req):
    param_string = ""

    if "params" in req:
        for key in sorted(req["params"]):
            param_string += key
            param_string += str(req["params"][key])

    sig_payload = req["method"] + str(req["id"]) + req["api_key"] + param_string + str(req["nonce"])

    req["sig"] = hmac.new(
        bytes(str(api_secret), "utf-8"),
        msg=bytes(sig_payload, "utf-8"),
        digestmod=hashlib.sha256
    ).hexdigest()

    return req
