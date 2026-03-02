from ..storage.trade_store import TradeStore
from ..constants import TradeState

class TradeStateMachine:
    def __init__(self, store: TradeStore):
        self.store = store

    async def transition(self, trade_id: int, new_state: TradeState, **kwargs):
        await self.store.update_state(trade_id, new_state, **kwargs)