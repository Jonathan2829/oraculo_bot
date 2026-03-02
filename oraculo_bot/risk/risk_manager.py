import time
from ..storage.trade_store import TradeStore
from ..storage.daily_tracker import DailyTracker
from ..config import Settings

SECTOR_GROUPS = {
    'ADA': 'L1', 'DOT': 'L1', 'SOL': 'L1',
    'DOGE': 'MEME', 'SHIB': 'MEME',
    'LINK': 'ORACLE', 'UNI': 'DEX',
}

def get_sector(symbol):
    base = symbol.split('/')[0]
    return SECTOR_GROUPS.get(base, 'OTHER')

class RiskManager:
    def __init__(self, settings: Settings, trade_store: TradeStore, daily_tracker: DailyTracker):
        self.settings = settings
        self.trade_store = trade_store
        self.daily_tracker = daily_tracker
        self.cooldowns = {}  # symbol -> timestamp
        self.consecutive_losses = 0

    async def can_trade(self, symbol: str, side: str) -> tuple[bool, str]:
        daily_pnl = await self.daily_tracker.get_today_pnl()
        if daily_pnl <= -self.settings.daily_max_loss_usdt:
            return False, "MAX_DAILY_LOSS"

        trades_last_hour = await self.trade_store.count_trades_last_hour()
        if trades_last_hour >= self.settings.max_trades_per_hour:
            return False, "MAX_TRADES_PER_HOUR"

        open_count = await self.trade_store.count_open_positions()
        if open_count >= self.settings.max_concurrent_positions:
            return False, "MAX_CONCURRENT"

        if symbol in self.cooldowns and time.time() < self.cooldowns[symbol]:
            return False, "SYMBOL_COOLDOWN"

        sector = get_sector(symbol)
        open_trades = await self.trade_store.get_open_trades()
        sector_count = sum(1 for t in open_trades if get_sector(t['symbol']) == sector)
        if sector_count >= 2:
            return False, "MAX_SECTOR_EXPOSURE"

        if self.consecutive_losses >= self.settings.max_consecutive_losses:
            return False, "MAX_CONSECUTIVE_LOSSES"

        return True, "OK"

    async def register_trade(self, trade_id: int, symbol: str):
        await self.daily_tracker.increment_trades()

    async def register_loss(self, symbol: str):
        self.cooldowns[symbol] = time.time() + self.settings.cooldown_after_loss_sec
        self.consecutive_losses += 1

    async def register_win(self, symbol: str):
        self.consecutive_losses = 0