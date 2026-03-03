import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Optional, Sequence, Tuple, List, Dict

# ============================================================
# SCHEMA compatible con TradeStore + reconciler + panel runtime
# ============================================================
SCHEMA = """
PRAGMA journal_mode=WAL;

-- =========================
-- TRADES (modelo "nuevo")
-- =========================
CREATE TABLE IF NOT EXISTS trades (
  trade_id INTEGER PRIMARY KEY AUTOINCREMENT,

  symbol TEXT NOT NULL,
  side   TEXT NOT NULL,
  state  TEXT NOT NULL,
  mode   TEXT,
  score  INTEGER,

  entry_price REAL,
  stop_price  REAL,
  tp1_price   REAL,
  tp2_price   REAL,

  -- compatibilidad extra (algunos módulos viejos)
  entry REAL,
  sl    REAL,
  tp    REAL,

  quantity REAL,
  qty REAL,         -- compatibilidad (si otro módulo usa qty)
  leverage INTEGER,

  pnl_realized REAL,
  pnl REAL,         -- compatibilidad (si otro módulo usa pnl)
  close_reason TEXT,

  created_ts INTEGER,
  updated_ts INTEGER,
  closed_ts  INTEGER,

  ts TEXT NOT NULL DEFAULT (datetime('now')) -- compatibilidad con tablas viejas
);

CREATE INDEX IF NOT EXISTS idx_trades_state  ON trades(state);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);

-- =========================
-- ORDERS (modelo "nuevo")
-- =========================
CREATE TABLE IF NOT EXISTS orders (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  trade_id INTEGER NOT NULL,

  binance_order_id TEXT,
  ts TEXT NOT NULL DEFAULT (datetime('now')),

  type   TEXT,
  status TEXT,
  price REAL,
  quantity REAL,
  filled_qty REAL,
  avg_price REAL,

  created_ts INTEGER,
  updated_ts INTEGER,

  raw_json TEXT,

  FOREIGN KEY(trade_id) REFERENCES trades(trade_id)
);

CREATE INDEX IF NOT EXISTS idx_orders_trade_id ON orders(trade_id);

-- =========================
-- DAILY STATS (modelo "nuevo")
-- =========================
CREATE TABLE IF NOT EXISTS daily_stats (
  date TEXT PRIMARY KEY,
  start_balance REAL,
  end_balance REAL,
  realized_pnl REAL,
  trades_count INTEGER
);

-- =========================
-- FUNDING HISTORY
-- =========================
CREATE TABLE IF NOT EXISTS funding_history (
  symbol TEXT NOT NULL,
  funding_rate REAL NOT NULL,
  timestamp INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_funding_symbol_ts ON funding_history(symbol, timestamp);

-- =========================
-- runtime_config + audit
-- =========================
CREATE TABLE IF NOT EXISTS runtime_config (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL DEFAULT (datetime('now')),
  actor_user_id TEXT NOT NULL,
  actor_name TEXT NOT NULL,
  action TEXT NOT NULL,
  payload TEXT NOT NULL
);
"""

# columnas mínimas esperadas (para migración ALTER)
TRADES_COLS: Dict[str, str] = {
    "trade_id": "INTEGER",
    "symbol": "TEXT",
    "side": "TEXT",
    "state": "TEXT",
    "mode": "TEXT",
    "score": "INTEGER",

    "entry_price": "REAL",
    "stop_price": "REAL",
    "tp1_price": "REAL",
    "tp2_price": "REAL",

    "entry": "REAL",
    "sl": "REAL",
    "tp": "REAL",

    "quantity": "REAL",
    "qty": "REAL",
    "leverage": "INTEGER",

    "pnl_realized": "REAL",
    "pnl": "REAL",
    "close_reason": "TEXT",

    "created_ts": "INTEGER",
    "updated_ts": "INTEGER",
    "closed_ts": "INTEGER",

    "ts": "TEXT",
}

ORDERS_COLS: Dict[str, str] = {
    "id": "INTEGER",
    "trade_id": "INTEGER",
    "binance_order_id": "TEXT",
    "ts": "TEXT",
    "type": "TEXT",
    "status": "TEXT",
    "price": "REAL",
    "quantity": "REAL",
    "filled_qty": "REAL",
    "avg_price": "REAL",
    "created_ts": "INTEGER",
    "updated_ts": "INTEGER",
    "raw_json": "TEXT",
}

DAILY_COLS: Dict[str, str] = {
    "date": "TEXT",
    "start_balance": "REAL",
    "end_balance": "REAL",
    "realized_pnl": "REAL",
    "trades_count": "INTEGER",
}


class DB:
    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)

    @contextmanager
    def _conn(self):
        con = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        try:
            yield con
            con.commit()
        finally:
            try:
                con.close()
            except Exception:
                pass

    def connect(self):
        return self._conn()

    def executescript(self, script: str) -> None:
        with self._lock, self._conn() as con:
            con.executescript(script)

    def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        with self._lock, self._conn() as con:
            con.execute(sql, params)

    def fetchone(self, sql: str, params: Sequence[Any] = ()) -> Optional[Tuple[Any, ...]]:
        with self._lock, self._conn() as con:
            cur = con.execute(sql, params)
            return cur.fetchone()

    def fetchall(self, sql: str, params: Sequence[Any] = ()) -> List[Tuple[Any, ...]]:
        with self._lock, self._conn() as con:
            cur = con.execute(sql, params)
            return cur.fetchall()


def _table_cols(con: sqlite3.Connection, table: str) -> List[str]:
    cur = con.execute(f"PRAGMA table_info({table})")
    return [row[1] for row in cur.fetchall()]


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    cur = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,))
    return cur.fetchone() is not None


def _add_missing_cols(con: sqlite3.Connection, table: str, cols: Dict[str, str]) -> None:
    existing = set(_table_cols(con, table))
    for name, ctype in cols.items():
        if name not in existing:
            con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ctype}")


def _rebuild_trades_id_to_trade_id(con: sqlite3.Connection) -> None:
    """
    Migra trades vieja con PK `id` hacia `trade_id`.
    """
    con.execute("ALTER TABLE trades RENAME TO trades_old")

    con.executescript("""
    CREATE TABLE trades (
      trade_id INTEGER PRIMARY KEY AUTOINCREMENT,

      symbol TEXT NOT NULL,
      side   TEXT NOT NULL,
      state  TEXT NOT NULL,
      mode   TEXT,
      score  INTEGER,

      entry_price REAL,
      stop_price  REAL,
      tp1_price   REAL,
      tp2_price   REAL,

      entry REAL,
      sl    REAL,
      tp    REAL,

      quantity REAL,
      qty REAL,
      leverage INTEGER,

      pnl_realized REAL,
      pnl REAL,
      close_reason TEXT,

      created_ts INTEGER,
      updated_ts INTEGER,
      closed_ts  INTEGER,

      ts TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_trades_state  ON trades(state);
    CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);
    """)

    old_cols = set(_table_cols(con, "trades_old"))
    new_cols = set(_table_cols(con, "trades"))

    insert_cols: List[str] = []
    select_parts: List[str] = []

    # id -> trade_id
    if "id" in old_cols:
        insert_cols.append("trade_id")
        select_parts.append("id")

    # resto de columnas comunes (excepto trade_id)
    for c in sorted(new_cols - {"trade_id"}):
        if c in old_cols:
            insert_cols.append(c)
            select_parts.append(c)

    if insert_cols:
        con.execute(
            f"INSERT INTO trades ({', '.join(insert_cols)}) "
            f"SELECT {', '.join(select_parts)} FROM trades_old"
        )

    con.execute("DROP TABLE trades_old")


def _rename_daily_day_to_date(con: sqlite3.Connection) -> None:
    """
    Migra daily_stats vieja `day` -> nueva `date`.
    """
    con.execute("ALTER TABLE daily_stats RENAME TO daily_stats_old")

    con.executescript("""
    CREATE TABLE daily_stats (
      date TEXT PRIMARY KEY,
      start_balance REAL,
      end_balance REAL,
      realized_pnl REAL,
      trades_count INTEGER
    );
    """)

    old_cols = set(_table_cols(con, "daily_stats_old"))
    if "day" in old_cols:
        con.execute("""
            INSERT INTO daily_stats (date, start_balance, end_balance, realized_pnl, trades_count)
            SELECT day, start_balance, end_balance, realized_pnl, trades_count
            FROM daily_stats_old
        """)

    con.execute("DROP TABLE daily_stats_old")


def _migrate(con: sqlite3.Connection) -> None:
    # trades
    if _table_exists(con, "trades"):
        cols = set(_table_cols(con, "trades"))
        if "trade_id" not in cols and "id" in cols:
            _rebuild_trades_id_to_trade_id(con)
        else:
            _add_missing_cols(con, "trades", TRADES_COLS)

    # orders
    if _table_exists(con, "orders"):
        _add_missing_cols(con, "orders", ORDERS_COLS)

    # daily_stats
    if _table_exists(con, "daily_stats"):
        cols = set(_table_cols(con, "daily_stats"))
        if "date" not in cols and "day" in cols:
            _rename_daily_day_to_date(con)
        else:
            _add_missing_cols(con, "daily_stats", DAILY_COLS)


def init_db(path: Optional[str] = None) -> DB:
    if not path:
        path = (os.getenv("DB_PATH") or "").strip() or "data/oraculo_bot.sqlite"

    db = DB(path)
    with db._lock, db._conn() as con:
        con.executescript(SCHEMA)
        _migrate(con)

    return db


Database = DB