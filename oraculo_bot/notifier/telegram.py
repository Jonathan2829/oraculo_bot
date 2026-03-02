import requests
import logging
import asyncio

log = logging.getLogger(__name__)

class TelegramNotifier:
    def __init__(self, token: str, chat_id: str, timeout: int = 10):
        self.token = token
        self.chat_id = chat_id
        self.timeout = timeout

    async def send(self, text: str):
        if not self.token or not self.chat_id:
            return
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

        def _post():
            try:
                requests.post(url, json=payload, timeout=self.timeout)
            except Exception as e:
                log.error(f"Telegram send error: {e}")

        await asyncio.to_thread(_post)