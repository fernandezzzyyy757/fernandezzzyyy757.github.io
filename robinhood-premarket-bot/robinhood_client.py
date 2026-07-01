"""Thin wrapper around robin_stocks (unofficial Robinhood API).

IMPORTANT: Robinhood has no public trading API. This uses a reverse-engineered
library that talks to the same endpoints as the mobile app. That is against
Robinhood's Terms of Service and could get an account flagged/restricted -
see README.md. Use at your own risk, and test with DRY_RUN=true first.

Also important: Robinhood only accepts LIMIT orders during extended hours
(premarket 7:00-9:30am ET / after-hours 4:00-6:00pm ET) - market orders are
rejected outside regular hours. This client always uses limit orders for the
premarket buy.
"""

import math
import time

import robin_stocks.robinhood as rh

from config import ROBINHOOD_USERNAME, ROBINHOOD_PASSWORD, SESSION_DIR, DRY_RUN


class RobinhoodError(Exception):
    pass


def login():
    if DRY_RUN:
        print("[robinhood] DRY_RUN is on - skipping real login.")
        return
    if not ROBINHOOD_USERNAME or not ROBINHOOD_PASSWORD:
        raise RobinhoodError("ROBINHOOD_USERNAME/ROBINHOOD_PASSWORD not set in .env")
    # store_session caches the auth token in SESSION_DIR so you're not asked
    # for MFA/device approval every single run. First login of the day will
    # likely still prompt for an SMS/app code interactively.
    rh.login(
        username=ROBINHOOD_USERNAME,
        password=ROBINHOOD_PASSWORD,
        store_session=True,
        pickle_path=SESSION_DIR,
    )


def logout():
    if not DRY_RUN:
        rh.logout()


def get_buying_power():
    if DRY_RUN:
        return 1000.0  # pretend amount for dry-run math; adjust as you like
    profile = rh.profiles.load_account_profile()
    return float(profile["buying_power"])


def get_extended_hours_price(symbol):
    """Prefer the extended-hours (premarket) trade price if Robinhood has
    one; fall back to the last regular-hours price."""
    if DRY_RUN:
        return None  # caller should use the scanner's premarket price instead
    quote = rh.stocks.get_quotes(symbol)[0]
    ext = quote.get("last_extended_hours_trade_price")
    return float(ext) if ext else float(quote["last_trade_price"])


def buy_limit_extended_hours(symbol, limit_price, dollars):
    """Buys as many whole shares as `dollars` covers, at `limit_price`,
    flagged for extended-hours execution. Whole shares only - Robinhood does
    not support fractional shares in extended hours."""
    quantity = math.floor(dollars / limit_price)
    if quantity < 1:
        raise RobinhoodError(
            f"Buying power ${dollars} is less than one share of {symbol} at ${limit_price}"
        )

    if DRY_RUN:
        print(
            f"[DRY_RUN] Would BUY {quantity} shares of {symbol} @ limit ${limit_price} "
            f"(extended hours) = ${round(quantity * limit_price, 2)}"
        )
        return {"id": "dry-run-buy", "quantity": quantity, "price": limit_price}

    order = rh.orders.order_buy_limit(
        symbol, quantity, limit_price, timeInForce="gfd", extendedHours=True
    )
    return order


def sell_market(symbol, quantity):
    if DRY_RUN:
        print(f"[DRY_RUN] Would SELL {quantity} shares of {symbol} @ market")
        return {"id": "dry-run-sell"}

    order = rh.orders.order_sell_market(symbol, quantity)
    return order


def get_order_status(order_id):
    if DRY_RUN:
        return "filled"
    order = rh.orders.get_stock_order_info(order_id)
    return order.get("state")


def wait_for_fill(order_id, timeout_sec=300, poll_sec=5):
    waited = 0
    while waited < timeout_sec:
        state = get_order_status(order_id)
        if state in ("filled", "rejected", "cancelled"):
            return state
        time.sleep(poll_sec)
        waited += poll_sec
    return "timeout"


def get_position_quantity(symbol):
    if DRY_RUN:
        return None  # caller tracks quantity from the dry-run buy result instead
    holdings = rh.account.build_holdings()
    position = holdings.get(symbol)
    return float(position["quantity"]) if position else 0.0

def get_current_price(symbol):
    if DRY_RUN:
        return None
    return float(rh.stocks.get_latest_price(symbol)[0])
