"""Discord 论坛前端：一个帖子 = 一个 conversation。

论坛频道（GUILD_FORUM）里每个帖子就是一个 thread，thread.id 天然是会话 key。
上下文不落盘——每轮从 thread.history 重建，Discord 就是数据库。
好处是重启/换机器都不丢，你在 Discord 里删一条消息上下文就真的变了。

运行:  python discord_bot.py
需要 .env 里有 DISCORD_BOT_TOKEN 和 DISCORD_FORUM_CHANNEL_ID
"""

import asyncio
import io
import os
import re

import anthropic
import discord

from core import Agent, Sink, build_system, load_tools

TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
FORUM_ID = int(os.getenv("DISCORD_FORUM_CHANNEL_ID", "0") or 0)
HISTORY_LIMIT = int(os.getenv("DISCORD_HISTORY_LIMIT", "40"))

DISCORD_LIMIT = 2000
PROGRESS_MARK = "⚙"  # 进度消息的前缀，重建历史时要跳过

# 论坛标签 → skill。标签名直接用 skill 名也行，这里给中文别名。
TAG_TO_SKILL = {
    "产品宣传": "xhs-product-promo",
    "干货": "xhs-howto",
    "去ai味": "xhs-de-ai",
    "配图": "xhs-image-style",
}


def split_for_discord(text: str, limit: int = DISCORD_LIMIT) -> list[str]:
    """按 Discord 2000 字上限切分，尽量切在段落边界，其次句子，最后才硬切。"""
    text = text.strip()
    if not text:
        return []
    chunks: list[str] = []
    while len(text) > limit:
        window = text[:limit]
        cut = window.rfind("\n\n")
        if cut < limit // 3:
            cut = window.rfind("\n")
        if cut < limit // 3:
            cut = max(window.rfind("。"), window.rfind("！"), window.rfind("？"))
            cut = cut + 1 if cut > limit // 3 else -1
        if cut < limit // 3:
            cut = limit  # 实在找不到边界就硬切
        chunks.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        chunks.append(text)
    return chunks


class ProgressSink(Sink):
    """把工具调用攒成进度行，交给外层去更新那条占位消息。"""

    def __init__(self):
        self.lines: list[str] = []
        self.dirty = False

    def tool_start(self, name: str, args: dict) -> None:
        brief = ", ".join(f"{k}={str(v)[:30]}" for k, v in args.items())
        self.lines.append(f"{name}({brief})")
        self.dirty = True

    def notice(self, msg: str) -> None:
        self.lines.append(f"⚠ {msg}")
        self.dirty = True

    def render(self) -> str:
        tail = self.lines[-6:]
        body = "\n".join(f"· {ln}" for ln in tail)
        return f"{PROGRESS_MARK} 处理中…\n{body}"[:DISCORD_LIMIT]


async def rebuild_history(thread: discord.Thread, me: discord.ClientUser) -> list:
    """从 thread 消息重建对话历史。

    只保留纯文本的 user/assistant 轮次——工具调用和 thinking block 不重建，
    模型看不到上一轮怎么调的工具，但看得到结论，对续写足够。
    """
    messages: list[dict] = []
    async for m in thread.history(limit=HISTORY_LIMIT, oldest_first=True):
        content = (m.content or "").strip()
        if not content or content.startswith(PROGRESS_MARK):
            continue
        role = "assistant" if m.author.id == me.id else "user"
        # 相邻同角色合并，避免出现连续两条 assistant
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"] += "\n" + content
        else:
            messages.append({"role": role, "content": content})
    # 历史必须以 user 开头
    while messages and messages[0]["role"] != "user":
        messages.pop(0)
    return messages


def skill_hint(thread: discord.Thread) -> str:
    """把帖子上的论坛标签翻译成给模型的 skill 提示。"""
    names = []
    for tag in getattr(thread, "applied_tags", []) or []:
        key = (tag.name or "").strip().lower().replace(" ", "")
        skill = TAG_TO_SKILL.get(key) or (tag.name if tag.name in TAG_TO_SKILL.values() else None)
        if skill:
            names.append(skill)
    if not names:
        return ""
    return ("这个帖子带了以下标签，对应的 skill 必须读并遵守："
            + "、".join(dict.fromkeys(names)))


class Bot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True  # 需要在开发者后台勾上 Message Content Intent
        super().__init__(intents=intents)
        self.tools, self.mcp_note = load_tools()
        self.busy: set[int] = set()  # 同一帖子同时只跑一轮

    async def on_ready(self):
        print(f"已登录：{self.user}（监听论坛 {FORUM_ID}）")
        print(f"工具 {len(self.tools)} 个 | {self.mcp_note}")

    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        thread = message.channel
        if not isinstance(thread, discord.Thread) or thread.parent_id != FORUM_ID:
            return
        if thread.id in self.busy:
            await message.reply("上一条还在处理，稍等一下。", mention_author=False)
            return

        self.busy.add(thread.id)
        try:
            await self._handle(thread, message)
        finally:
            self.busy.discard(thread.id)

    async def _handle(self, thread: discord.Thread, message: discord.Message):
        history = await rebuild_history(thread, self.user)
        # 最后一条就是刚收到的这条，交给 chat() 去 append，别重复
        if history and history[-1]["role"] == "user":
            current = history.pop()["content"]
        else:
            current = message.content

        agent = Agent(client=anthropic.Anthropic(), tools=self.tools,
                      system=build_system(skill_hint(thread)))
        agent.load_history(history)

        sink = ProgressSink()
        placeholder = await thread.send(f"{PROGRESS_MARK} 处理中…")

        async def tick():
            """把工具调用进度刷到那条占位消息上，免得看起来像死了。"""
            while True:
                await asyncio.sleep(2)
                if sink.dirty:
                    sink.dirty = False
                    try:
                        await placeholder.edit(content=sink.render())
                    except discord.HTTPException:
                        pass

        ticker = asyncio.create_task(tick())
        try:
            async with thread.typing():
                # core 里的 client 是同步阻塞的，直接跑会卡死整个事件循环，
                # 其它帖子也没法回。丢到线程里去。
                reply = await asyncio.to_thread(agent.chat, current, sink)
        except anthropic.APIStatusError as e:
            reply = f"API 报错 {e.status_code}：{e.message}"
        except Exception as e:
            reply = f"出错了：{type(e).__name__}: {e}"
        finally:
            ticker.cancel()

        chunks = split_for_discord(reply) or ["（这轮没有输出）"]
        await placeholder.edit(content=chunks[0])
        for c in chunks[1:]:
            await thread.send(c)

        await self._send_images(thread, reply)

    async def _send_images(self, thread: discord.Thread, reply: str):
        """正文里如果出现了出图 URL，下载后作为附件发——CDN 链接不知道能活多久。"""
        for url in re.findall(r"https?://\S+\.(?:png|jpg|jpeg|webp)", reply)[:4]:
            try:
                data = await asyncio.to_thread(_fetch, url)
                await thread.send(file=discord.File(io.BytesIO(data), "cover.png"))
            except Exception:
                pass  # 发不出去就算了，URL 已经在正文里


def _fetch(url: str) -> bytes:
    import urllib.request
    with urllib.request.urlopen(url, timeout=120) as r:
        return r.read()


def main() -> int:
    if not TOKEN:
        print("缺 DISCORD_BOT_TOKEN，去 .env 里填")
        return 1
    if not FORUM_ID:
        print("缺 DISCORD_FORUM_CHANNEL_ID（右键论坛频道 → 复制频道 ID）")
        return 1
    Bot().run(TOKEN, log_handler=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
