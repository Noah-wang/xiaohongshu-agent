"""接 xiaohongshu-mcp（https://github.com/xpzouying/xiaohongshu-mcp）。

只接入只读工具。发布、评论、点赞这些写操作会直接动你的真实账号，
现在一律不接——需要的时候要单独加确认门，不能让模型自己决定。

服务没起、连不上都不影响主流程：load() 返回空列表，agent 少几个工具照常跑。
"""

import asyncio
import os

# 白名单。想加新工具改这里，但加之前先确认它是只读的。
READONLY_TOOLS = {"search_feeds", "get_feed_detail", "list_feeds", "user_profile"}

MCP_URL = os.getenv("XHS_MCP_URL", "")
MCP_TOKEN = os.getenv("XHS_MCP_TOKEN", "")

_TOOL_NAMES: set[str] = set()


def _headers() -> dict:
    return {"Authorization": f"Bearer {MCP_TOKEN}"} if MCP_TOKEN else {}


async def _connect(fn):
    """开一条连接跑一次 fn(session)。CLI 场景每次现连，够用且不会有连接悬挂。"""
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with httpx2.AsyncClient(headers=_headers(), timeout=60) as http:
        async with streamable_http_client(MCP_URL, http_client=http) as streams:
            read, write = streams[0], streams[1]
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await fn(session)


def load() -> tuple[list[dict], str]:
    """返回 (工具定义列表, 说明)。连不上就返回空列表，不抛异常。"""
    global _TOOL_NAMES
    if not MCP_URL:
        return [], "未配置 XHS_MCP_URL，跳过小红书 MCP"

    async def _list(session):
        return await session.list_tools()

    try:
        result = asyncio.run(asyncio.wait_for(_connect(_list), timeout=20))
    except Exception as e:
        return [], f"连不上 {MCP_URL}（{type(e).__name__}），跳过小红书 MCP"

    tools = []
    for t in result.tools:
        if t.name not in READONLY_TOOLS:
            continue
        tools.append({
            "name": t.name,
            "description": (t.description or "")[:800],
            # mcp 2.x 用 input_schema，1.x 用 inputSchema，两个都认
            "input_schema": (getattr(t, "input_schema", None)
                             or getattr(t, "inputSchema", None)
                             or {"type": "object", "properties": {}}),
        })
    _TOOL_NAMES = {t["name"] for t in tools}

    skipped = len(result.tools) - len(tools)
    return tools, f"已接入 {len(tools)} 个只读工具（跳过 {skipped} 个写操作/登录工具）"


def owns(name: str) -> bool:
    return name in _TOOL_NAMES


def call(name: str, args: dict) -> str:
    async def _call(session):
        return await session.call_tool(name, args)

    try:
        # 首次调用要冷启浏览器，实测可超过 120s；热起来之后大约 15s
        result = asyncio.run(asyncio.wait_for(_connect(_call), timeout=300))
    except BaseException as e:
        # ExceptionGroup 默认只打印 "1 sub-exception"，真正的原因藏在子异常里
        if isinstance(e, BaseExceptionGroup):
            subs = "; ".join(f"{type(x).__name__}: {x}" for x in e.exceptions)
            return f"调用 {name} 失败: {subs}"
        return f"调用 {name} 失败: {type(e).__name__}: {e}"

    parts = []
    for c in result.content:
        parts.append(getattr(c, "text", None) or str(c))
    out = "\n".join(parts)
    # 搜索结果可能很长，截断避免一次性撑爆上下文
    return out[:20000] + ("\n…(已截断)" if len(out) > 20000 else "")
