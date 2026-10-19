"""課題一覧を返すDiscord bot。常時起動して使う。

    !worklist         未提出と提出済みの両方
    !worklist todo    未提出だけ
    !worklist done    提出済みだけ

個人情報が出るため、DISCORD_ALLOWED_USER_IDS に書いたユーザー以外には応答しない。
"""
import asyncio
import os
import sys
import time
from pathlib import Path

import discord

from notify import load_env
from worklist import build_reply

COMMANDS = ("!worklist", "!workls", "!課題")
CACHE_SECONDS = 60
_cache: dict[str, tuple[float, list[str]]] = {}


def get_reply(show: str) -> list[str]:
    cached = _cache.get(show)
    if cached and time.time() - cached[0] < CACHE_SECONDS:
        return cached[1]
    chunks = build_reply(show)
    _cache[show] = (time.time(), chunks)
    return chunks


def main() -> int:
    load_env(Path(__file__).with_name(".env"))
    bot_token = os.environ.get("DISCORD_BOT_TOKEN", "")
    allowed = {int(x) for x in os.environ.get("DISCORD_ALLOWED_USER_IDS", "").replace(" ", "").split(",") if x}
    if not bot_token or not allowed:
        print("DISCORD_BOT_TOKEN と DISCORD_ALLOWED_USER_IDS を .env に設定してください。", file=sys.stderr)
        return 2

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        print(f"ログインしました: {client.user}")

    @client.event
    async def on_message(message: discord.Message):
        if message.author.bot or message.author.id not in allowed:
            return
        parts = message.content.strip().split()
        if not parts or parts[0] not in COMMANDS:
            return
        arg = parts[1].lower() if len(parts) > 1 else "both"
        show = {"todo": "todo", "done": "done"}.get(arg, "both")
        async with message.channel.typing():
            try:
                chunks = await asyncio.to_thread(get_reply, show)
            except Exception as error:
                await message.reply(f"取得に失敗しました: {error}")
                return
        for chunk in chunks:
            await message.channel.send(chunk)

    client.run(bot_token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
