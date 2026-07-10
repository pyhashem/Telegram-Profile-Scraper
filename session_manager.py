import os
import time
import asyncio
from loguru import logger
from telethon import TelegramClient
from telethon.errors import FloodWaitError, UnauthorizedError
from telethon import functions


def extract_freeze_dates(d: dict) -> dict:
    result = {}
    app_config = d.get("app_config", {})
    for param in app_config.get("rows", []):
        if param.get("_") == "jsonObjectValue":
            key = param.get("key", "")
            if "freeze" in key.lower():
                val = param.get("value", {})
                if val.get("_") == "jsonNumber":
                    result["freeze_since_date"] = val.get("value", 0)
    return result


async def is_frozen(client: TelegramClient) -> bool:
    result = await client(functions.help.GetAppConfigRequest(hash=0))
    freeze: dict = extract_freeze_dates(result.to_dict())
    return freeze.get("freeze_since_date", 0) > 0


class SessionManager:
    def __init__(self, sessions_dir: str, proxy: tuple | None = None):
        self.sessions_dir = sessions_dir
        self.clients: list[TelegramClient] = []
        self._index = 0
        self._paused: dict[int, float] = {}
        self._proxy = proxy

    def load_sessions(self, api_id: int, api_hash: str):
        session_files = [
            f for f in os.listdir(self.sessions_dir)
            if f.endswith(".session")
        ]
        if not session_files:
            raise FileNotFoundError(f"No .session files found in {self.sessions_dir}")
        for sf in session_files:
            path = os.path.join(self.sessions_dir, sf)
            client = TelegramClient(path, api_id, api_hash, proxy=self._proxy)
            self.clients.append(client)
            if self._proxy:
                logger.info(f"Loaded session: {sf} -> proxy {self._proxy[1]}:{self._proxy[2]}")
            else:
                logger.info(f"Loaded session: {sf} -> direct")

    async def start_all(self):
        valid = []
        for i, client in enumerate(self.clients):
            await client.connect()
            try:
                if not await client.is_user_authorized():
                    logger.warning(f"Session {i} not authorized, skipping")
                    await client.disconnect()
                    continue
            except UnauthorizedError:
                logger.warning(f"Session {i} unauthorized, skipping")
                await client.disconnect()
                continue
            try:
                if await is_frozen(client):
                    logger.warning(f"Session {i} is frozen, skipping")
                    await client.disconnect()
                    continue
            except Exception as e:
                logger.debug(f"Could not check freeze status for session {i}: {e}")
            logger.info(f"Session {i} connected and verified")
            valid.append(client)
        self.clients = valid
        if not self.clients:
            raise RuntimeError("No valid sessions available")

    async def stop_all(self):
        for client in self.clients:
            await client.disconnect()

    def get_client(self) -> TelegramClient:
        now = time.time()
        available = [
            i for i in range(len(self.clients))
            if i not in self._paused or now >= self._paused[i]
        ]
        if not available:
            wait_until = min(self._paused.values())
            wait_seconds = max(1, int(wait_until - now))
            raise FloodWaitError(request=None, capture=wait_seconds)
        idx = available[self._index % len(available)]
        self._index += 1
        return self.clients[idx]

    def pause_client(self, client: TelegramClient, seconds: int):
        for i, c in enumerate(self.clients):
            if c is client:
                self._paused[i] = time.time() + seconds
                break

    async def execute_with_rotation(self, coro_func, *args, **kwargs):
        max_retries = 10
        retries = 0
        while True:
            client = self.get_client()
            try:
                return await coro_func(client, *args, **kwargs)
            except FloodWaitError as e:
                retries += 1
                if retries >= max_retries:
                    logger.error(f"Max retries ({max_retries}) reached due to FloodWait, giving up")
                    raise
                logger.warning(f"FloodWait: pausing client for {e.seconds}s")
                self.pause_client(client, e.seconds)
                await asyncio.sleep(min(e.seconds, 60))
