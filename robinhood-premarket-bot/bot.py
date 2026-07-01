"""Main orchestrator. Run this with `python bot.py` starting before your
SCAN_TIME each trading day (and run `python dashboard.py` alongside it so you
can approve/reject from your browser at http://localhost:5055).

Flow per day:
  1. At SCAN_TIME, scan the universe for the single best premarket candidate.
  2. If one qualifies, propose it on the dashboard and wait for your approval
     (up to ENTRY_DEADLINE).
  3. If approved, place a limit buy (extended hours) for your full buying
     power in that one ticker.
  4. After the position fills, wait until EXIT_CHECK_DELAY_MIN after market
     open (or a profit target/stop loss is hit), then propose a sell.
  5. If approved (or REQUIRE_EXIT_APPROVAL is False), sell and log the trade.

Everything runs through DRY_RUN=true by default - no real orders are placed
until you flip that off in .env.
"""

import time
from datetime import datetime, timedelta

import config
import state
import scanner
import robinhood_client as rh_client


def now_et():
    return datetime.now(config.ET)


def today_at(hhmm):
    hh, mm = map(int, hhmm.split(":"))
    return now_et().replace(hour=hh, minute=mm, second=0, microsecond=0)


def run_scan_and_propose():
    print(f"[bot] Running premarket scan at {now_et()}")
    from_date = (now_et() - timedelta(days=1)).strftime("%Y-%m-%d")
    to_date = now_et().strftime("%Y-%m-%d")

    candidates = scanner.scan(from_date=from_date, to_date=to_date)
    if not candidates:
        print("[bot] No qualifying premarket candidate today.")
        state.update(status="idle")
        return

    best = candidates[0]
    print(f"[bot] Best candidate: {best['symbol']} (score {best['score']})")
    print(scanner.build_reasoning(best))

    buying_power = rh_client.get_buying_power()
    est_shares = int(buying_power // best["premarket_price"])

    proposal = {
        **best,
        "dollars": round(buying_power, 2),
        "est_shares": est_shares,
        "entry_time": now_et().strftime("%H:%M ET"),
        "expires_at": today_at(config.ENTRY_DEADLINE).strftime("%H:%M ET"),
    }
    state.update(status="proposed_entry", proposal=proposal, decision=None)


def wait_for_entry_decision():
    deadline = today_at(config.ENTRY_DEADLINE)
    print(f"[bot] Waiting for entry approval on the dashboard until {deadline.strftime('%H:%M')} ET...")
    while now_et() < deadline:
        s = state.load()
        if s.get("decision") == "approved":
            return "approved"
        if s.get("decision") == "rejected":
            return "rejected"
        time.sleep(10)
    return "expired"


def execute_entry():
    s = state.load()
    proposal = s["proposal"]
    symbol = proposal["symbol"]
    limit_price = round(proposal["premarket_price"] * 1.003, 2)  # small buffer to help it fill

    print(f"[bot] Buying {symbol} @ limit ${limit_price}, ${proposal['dollars']} buying power")
    order = rh_client.buy_limit_extended_hours(symbol, limit_price, proposal["dollars"])
    fill_state = rh_client.wait_for_fill(order["id"])
    print(f"[bot] Order state: {fill_state}")

    if fill_state not in ("filled",) and not config.DRY_RUN:
        print("[bot] Order did not fill - aborting for today.")
        state.update(status="idle", proposal=None)
        return None

    quantity = order.get("quantity") or rh_client.get_position_quantity(symbol)
    position = {
        "symbol": symbol,
        "quantity": quantity,
        "fill_price": limit_price,
        "filled_at": now_et().strftime("%H:%M ET"),
        "order_id": order["id"],
    }
    state.update(status="entered", position=position)
    return position


def propose_exit(position, reason):
    symbol = position["symbol"]
    current_price = rh_client.get_current_price(symbol) or position["fill_price"]
    pl_pct = round((current_price - position["fill_price"]) / position["fill_price"] * 100, 2)

    exit_proposal = {
        "symbol": symbol,
        "current_price": current_price,
        "pl_pct": pl_pct,
        "reason": reason,
    }
    state.update(status="proposed_exit", exit_proposal=exit_proposal, exit_decision=None)
    return exit_proposal


def wait_for_exit_decision(timeout_min=30):
    if not config.REQUIRE_EXIT_APPROVAL:
        return "approved"
    deadline = now_et() + timedelta(minutes=timeout_min)
    print("[bot] Waiting for exit approval on the dashboard...")
    while now_et() < deadline:
        s = state.load()
        if s.get("exit_decision") == "approved":
            return "approved"
        if s.get("exit_decision") == "rejected":
            return "rejected"
        time.sleep(10)
    return "timeout"


def execute_exit(position):
    symbol = position["symbol"]
    quantity = position["quantity"]
    order = rh_client.sell_market(symbol, quantity)
    rh_client.wait_for_fill(order["id"])

    sell_price = rh_client.get_current_price(symbol) or position["fill_price"]
    pl_pct = round((sell_price - position["fill_price"]) / position["fill_price"] * 100, 2)

    s = state.load()
    history = s.get("history", [])
    history.append({
        "symbol": symbol,
        "date": now_et().strftime("%Y-%m-%d"),
        "buy_price": position["fill_price"],
        "sell_price": sell_price,
        "pl_pct": pl_pct,
    })
    state.update(status="idle", position=None, exit_proposal=None, history=history)
    print(f"[bot] Sold {symbol} @ ${sell_price} ({pl_pct}% P/L)")


def monitor_position_and_exit(position):
    exit_time = now_et() + timedelta(minutes=config.EXIT_CHECK_DELAY_MIN)
    print(f"[bot] Holding {position['symbol']}; will re-check for exit around {exit_time.strftime('%H:%M')} ET")

    while True:
        current_price = rh_client.get_current_price(position["symbol"]) or position["fill_price"]
        pl_pct = (current_price - position["fill_price"]) / position["fill_price"] * 100

        hit_target = pl_pct >= config.PROFIT_TARGET_PCT
        hit_stop = pl_pct <= config.STOP_LOSS_PCT
        time_reached = now_et() >= exit_time

        if hit_target or hit_stop or time_reached:
            if hit_target:
                reason = f"Profit target of {config.PROFIT_TARGET_PCT}% reached ({round(pl_pct, 2)}%)."
            elif hit_stop:
                reason = f"Stop loss of {config.STOP_LOSS_PCT}% reached ({round(pl_pct, 2)}%)."
            else:
                reason = f"{config.EXIT_CHECK_DELAY_MIN} minutes after market open."

            propose_exit(position, reason)
            decision = wait_for_exit_decision()
            if decision == "approved":
                execute_exit(position)
                return
            elif decision == "rejected":
                print("[bot] Exit rejected - will re-check again shortly.")
                exit_time = now_et() + timedelta(minutes=5)
                state.update(status="entered")
            else:
                print("[bot] No exit decision in time - re-checking shortly.")
                exit_time = now_et() + timedelta(minutes=5)
                state.update(status="entered")

        time.sleep(30)


def main():
    print("[bot] Starting. DRY_RUN =", config.DRY_RUN)
    rh_client.login()
    last_run_date = None

    while True:
        today = now_et().strftime("%Y-%m-%d")

        if today != last_run_date and now_et() >= today_at(config.SCAN_TIME):
            state.reset_for_new_day(today)
            run_scan_and_propose()
            last_run_date = today

            s = state.load()
            if s["status"] == "proposed_entry":
                decision = wait_for_entry_decision()
                if decision == "approved":
                    position = execute_entry()
                    if position:
                        monitor_position_and_exit(position)
                elif decision == "rejected":
                    print("[bot] Entry rejected by user.")
                    state.update(status="idle", proposal=None)
                else:
                    print("[bot] Entry proposal expired unapproved.")
                    state.update(status="expired", proposal=None)

        time.sleep(30)


if __name__ == "__main__":
    main()
