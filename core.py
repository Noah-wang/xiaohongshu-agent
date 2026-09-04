"""Agent 内核。前端无关——CLI 和 Discord 共用这一份。

输出通过 Sink 抛出去，内核本身不 print。想接新前端就实现一个 Sink。
"""

import os

import anthropic
from dotenv import load_dotenv

load_dotenv(override=True)

from tools import local, usage, xhs_mcp  # noqa: E402

MODEL = os.getenv("AGENT_MODEL", "deepseek-v4-flash")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "8000"))
MAX_TOOL_ROUNDS = int(os.getenv("MAX_TOOL_ROUNDS", "12"))

BASE_SYSTEM = """你是一个小红书内容助手，擅长选题、标题、正文和话题标签。
回答简洁、口语化，不要写多余的客套话。

重要：小红书不渲染 markdown，绝对不要用 #、##、**、``` 这类语法。
需要强调就用 emoji 或者换行分段，标题直接写文字。

工作方式：
- 动笔写之前，先用 read_skill 读对应的写作 skill，按它的规范写
- 写自有产品的帖子，先用 read_product 读产品档案，不要凭印象编造
- 要配图时先读 xhs-image-style，按里面的固定后缀拼 prompt，再调 generate_image
- 稿子成型后，用 xhs-de-ai 自查一遍再交给用户；用户说"太 AI 了"也走这个
- 稿子给用户看过、用户确认满意之后，才调 save_note 存稿"""


def build_system(extra: str = "") -> str:
    """把 skill / 产品索引拼进 system prompt。

    索引短且稳定，放 system prompt 比做成 list_skills 工具省一次往返，
    也更容易命中 prompt cache。全文才按需用 read_skill 拉。
    """
    parts = [BASE_SYSTEM]

    skills = local.skill_index()
    if skills:
        parts.append("可用的 skill（用 read_skill 读全文）：\n"
                     + "\n".join(f"- {n}：{d}" for n, d in skills))

    products = local.product_index()
    if products:
        parts.append("自有产品档案（用 read_product 读全文）：\n"
                     + "\n".join(f"- {n}：{d}" for n, d in products))

    if extra:
        parts.append(extra)

    return "\n\n".join(parts)


def load_tools() -> tuple[list[dict], str]:
    mcp_tools, note = xhs_mcp.load()
    return local.TOOLS + mcp_tools, note


# ---------------------------------------------------------------- 输出

class Sink:
    """内核把过程事件抛给它。默认全部丢弃。"""

    def thinking(self, delta: str) -> None: ...
    def text(self, delta: str) -> None: ...
    def tool_start(self, name: str, args: dict) -> None: ...
    def tool_done(self, name: str, out: str) -> None: ...
    def notice(self, msg: str) -> None: ...


# ---------------------------------------------------------------- Agent

class Agent:
    """维护对话历史 + 执行工具。每轮把全量历史发给模型。"""

    def __init__(self, client: anthropic.Anthropic, tools: list[dict],
                 model: str = MODEL, system: str | None = None):
        self.client = client
        self.model = model
        self.system = system or build_system()
        self.tools = tools
        self.messages: list[anthropic.types.MessageParam] = []

    def reset(self) -> None:
        self.messages.clear()

    def load_history(self, messages: list) -> None:
        """用外部历史替换当前上下文（Discord 从 thread 重建时用）。"""
        self.messages = list(messages)

    # ------------------------------------------------------------ 单次请求

    def _stream_once(self, sink: Sink):
        """发一次请求。返回 final message；额度耗尽返回 None。"""
        with self.client.messages.stream(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=self.system,
            tools=self.tools,
            # 让思考过程可见，否则前端会干等一段没有输出。
            # DeepSeek 走中转站时这个参数是 no-op（它本来就返回 thinking block），
            # 换回 claude-opus-5 时才真正生效。
            thinking={"type": "adaptive", "display": "summarized"},
            messages=self.messages,
        ) as stream:
            for event in stream:
                if event.type != "content_block_delta":
                    continue
                if event.delta.type == "thinking_delta":
                    sink.thinking(event.delta.thinking)
                elif event.delta.type == "text_delta":
                    sink.text(event.delta.text)

            final = stream.get_final_message()

        if getattr(final, "usage", None):
            usage.record(self.model, final.usage)

        text = "".join(b.text for b in final.content if b.type == "text")

        # max_tokens 是思考和正文共用的额度。推理模型可能把额度全烧在思考上，
        # 结果 content 里只有 thinking 没有 text——不报错，但一个字都没输出。
        if final.stop_reason == "max_tokens" and not text.strip() \
                and not any(b.type == "tool_use" for b in final.content):
            sink.notice(f"模型把 {MAX_TOKENS} tokens 全用在思考上了，没有输出正文。"
                        f"可以简化问题重问，或调大 .env 里的 MAX_TOKENS。")
            return None

        if final.stop_reason == "max_tokens":
            sink.notice(f"回答在 {MAX_TOKENS} tokens 处被截断")

        return final

    # ------------------------------------------------------------ 工具派发

    def _dispatch(self, name: str, args: dict) -> str:
        """加一个工具 = TOOLS 加一条 + HANDLERS 加一行，这里不用动。"""
        try:
            if name in local.HANDLERS:
                return str(local.HANDLERS[name](**args))
            if xhs_mcp.owns(name):
                return xhs_mcp.call(name, args)
            return f"没有叫 {name} 的工具"
        except Exception as e:
            # 工具报错要作为 tool_result 回给模型，让它自己换个方式，
            # 而不是把整个对话崩掉。
            return f"工具执行出错: {type(e).__name__}: {e}"

    # ------------------------------------------------------------ 主流程

    def chat(self, user_input: str, sink: Sink | None = None) -> str:
        """跑完一轮（含工具循环），返回模型最终的文字回复。"""
        sink = sink or Sink()
        self.messages.append({"role": "user", "content": user_input})
        rollback_to = len(self.messages) - 1
        last_text = ""

        for rounds in range(1, MAX_TOOL_ROUNDS + 1):
            final = self._stream_once(sink)
            if final is None:
                del self.messages[rollback_to:]  # 这轮死了，回滚干净
                return ""

            # 存整个 content：thinking 和 tool_use block 都要原样带回下一轮。
            self.messages.append({"role": "assistant", "content": final.content})
            last_text = "".join(b.text for b in final.content if b.type == "text")

            if final.stop_reason != "tool_use":
                # 推理模型偶尔会以 end_turn 正常结束、但一个 text block 都不产出。
                # 这条路径不归 _stream_once 的 max_tokens 保护管，会静默返回空串，
                # 前端只能显示「这轮没有输出」，看不出为什么。
                if not last_text.strip():
                    sink.notice(
                        f"模型结束了这一轮却没写正文"
                        f"（stop_reason={final.stop_reason}，工具调用 {rounds} 轮）。"
                        f"重发一次通常就好；反复出现就把问题拆细，或调大 MAX_TOKENS。")
                return last_text

            results = []
            for block in final.content:
                if block.type != "tool_use":
                    continue
                args = dict(block.input)
                sink.tool_start(block.name, args)
                out = self._dispatch(block.name, args)
                sink.tool_done(block.name, out)
                results.append({
                    "type": "tool_result", "tool_use_id": block.id, "content": out,
                })

            # 一条 user 消息里放回全部 tool_result，不要拆成多条。
            self.messages.append({"role": "user", "content": results})

        sink.notice(f"工具调用超过 {MAX_TOOL_ROUNDS} 轮，停下了。")
        return last_text
