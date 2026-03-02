# Reemplazado por tenacity, este archivo se puede eliminar o mantener como wrapper.
# Mantenemos solo por compatibilidad.
import logging
from typing import Callable, Any

log = logging.getLogger(__name__)

class BinanceErrorHandler:
    @staticmethod
    async def with_retry(func: Callable, *args, **kwargs) -> Any:
        return await func(*args, **kwargs)