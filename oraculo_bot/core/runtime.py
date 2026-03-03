import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Dict


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_str(v: Any) -> str:
    if isinstance(v, (dict, list, tuple)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def _from_str(s: str) -> Any:
    s = (s or "").strip()
    if s == "":
        return ""
    # try json
    if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
        try:
            return json.loads(s)
        except Exception:
            return s
    # try bool
    low = s.lower()
    if low in ("true", "1", "yes", "y", "on"):
        return True
    if low in ("false", "0", "no", "n", "off"):
        return False
    # try int/float
    try:
        if "." in s:
            return float(s)
        return int(s)
    except Exception:
        return s


@dataclass
class RuntimeState:
    """
    Estado operativo en caliente.
    Se guarda en SQLite vía RuntimeStore.
    """
    paused: bool = False
    auto_trading: bool = False
    risk_per_trade: float = 0.5  # % por trade (ej 0.5 = 0.5%)
    leverage_default: int = 8
    max_positions: int = 1
    scan_interval_seconds: int = 60
    whitelist_symbols: Optional[list[str]] = None  # None = todo permitido


class RuntimeStore:
    def __init__(self, db):
        """
        db: tu wrapper/conexión SQLite.
        Debe exponer: execute(sql, params) + fetchone/fetchall.
        """
        self.db = db

    def _set(self, key: str, value: Any):
        val = _to_str(value)
        ts = _utc_now()
        self.db.execute(
            "INSERT INTO runtime_config(key,value,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, val, ts),
        )

    def _get(self, key: str, default: Any = None) -> Any:
        row = self.db.fetchone("SELECT value FROM runtime_config WHERE key=?", (key,))
        if not row:
            return default
        return _from_str(row[0])

    def ensure_defaults(self, defaults: RuntimeState):
        # Solo setea si NO existen
        for k, v in defaults.__dict__.items():
            existing = self.db.fetchone("SELECT 1 FROM runtime_config WHERE key=?", (k,))
            if not existing:
                self._set(k, v)

    def load_state(self) -> RuntimeState:
        rows = self.db.fetchall("SELECT key,value FROM runtime_config", ())
        m: Dict[str, Any] = {}
        for k, v in rows:
            m[k] = _from_str(v)

        st = RuntimeState()
        for k in st.__dict__.keys():
            if k in m:
                setattr(st, k, m[k])

        # normaliza whitelist
        if isinstance(st.whitelist_symbols, str):
            st.whitelist_symbols = [x.strip().upper() for x in st.whitelist_symbols.split(",") if x.strip()]
        if st.whitelist_symbols is not None:
            st.whitelist_symbols = [x.strip().upper() for x in st.whitelist_symbols if str(x).strip()]

        # tipos duros
        st.paused = bool(st.paused)
        st.auto_trading = bool(st.auto_trading)
        st.risk_per_trade = float(st.risk_per_trade)
        st.leverage_default = int(st.leverage_default)
        st.max_positions = int(st.max_positions)
        st.scan_interval_seconds = int(st.scan_interval_seconds)

        return st

    def update(self, **kwargs):
        for k, v in kwargs.items():
            self._set(k, v)

    def audit(self, actor_user_id: str, actor_name: str, action: str, payload: dict):
        self.db.execute(
            "INSERT INTO audit_log(ts,actor_user_id,actor_name,action,payload) VALUES(?,?,?,?,?)",
            (_utc_now(), str(actor_user_id), actor_name, action, json.dumps(payload, ensure_ascii=False)),
        )