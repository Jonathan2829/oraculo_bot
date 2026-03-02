import sqlite3
from collections import defaultdict

DB_PATH = "oraculo_bot.sqlite"

def q(con, sql, args=()):
    cur = con.execute(sql, args)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]

def main():
    con = sqlite3.connect(DB_PATH)
    try:
        trades = q(con, "SELECT * FROM trades")
        orders = q(con, "SELECT * FROM orders")
        order_map = {}
        for o in orders:
            tid = o["trade_id"]
            if tid not in order_map:
                order_map[tid] = {}
            order_map[tid][o["type"]] = o

        total = len(trades)
        closed = sum(1 for t in trades if t["state"] == "DONE")
        open_ = total - closed

        print(f"TOTAL TRADES: {total}")
        print(f"CERRADOS: {closed}")
        print(f"ABIERTOS: {open_}\n")

        outcome_counts = defaultdict(int)
        rsum = 0.0
        rcount = 0
        pnl_sum = 0.0
        for t in trades:
            if t["state"] != "DONE":
                continue
            reason = t.get("close_reason")
            if reason:
                outcome_counts[reason] += 1
            pnl = t.get("pnl_realized")
            if pnl is not None:
                pnl_sum += pnl
            entry = t["entry_price"]
            sl = t["stop_price"]
            tp1 = t["tp1_price"]
            if entry and sl and entry > 0:
                r = abs(entry - sl)
                if r > 0:
                    if reason == "TP":
                        rmult = abs(tp1 - entry) / r
                        rsum += rmult
                        rcount += 1
                    elif reason == "SL":
                        rsum += -1.0
                        rcount += 1

        print("OUTCOMES (por close_reason):")
        for k, v in sorted(outcome_counts.items(), key=lambda x: -x[1]):
            print(f"  {k}: {v}")
        if rcount:
            print(f"\nR promedio (TP/SL): {rsum/rcount:.3f}")
        print(f"\nPnL total realizado: {pnl_sum:.2f} USDT")

        sym_stats = defaultdict(lambda: {"total":0, "closed":0, "tp":0, "sl":0, "r_sum":0.0, "r_n":0, "pnl":0.0})
        for t in trades:
            sym = t["symbol"]
            sym_stats[sym]["total"] += 1
            if t["state"] == "DONE":
                sym_stats[sym]["closed"] += 1
                reason = t.get("close_reason")
                if reason == "TP":
                    sym_stats[sym]["tp"] += 1
                elif reason == "SL":
                    sym_stats[sym]["sl"] += 1
                pnl = t.get("pnl_realized")
                if pnl is not None:
                    sym_stats[sym]["pnl"] += pnl
                entry = t["entry_price"]
                sl = t["stop_price"]
                tp1 = t["tp1_price"]
                if entry and sl and entry > 0:
                    r = abs(entry - sl)
                    if r > 0:
                        if reason == "TP":
                            rmult = abs(tp1 - entry) / r
                            sym_stats[sym]["r_sum"] += rmult
                            sym_stats[sym]["r_n"] += 1
                        elif reason == "SL":
                            sym_stats[sym]["r_sum"] += -1.0
                            sym_stats[sym]["r_n"] += 1

        print("\nTOP símbolos por PnL total:")
        rows = []
        for sym, s in sym_stats.items():
            rows.append((sym, s["pnl"], s["closed"]))
        rows.sort(key=lambda x: x[1], reverse=True)
        for sym, pnl, n in rows[:15]:
            print(f"  {sym:10s} PnL={pnl:.2f} closed={n}")

    finally:
        con.close()

if __name__ == "__main__":
    main()