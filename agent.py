"""小红书内容 Agent。

运行:  python agent.py
退出:  输入 exit / quit，或按 Ctrl-C
重置:  输入 /reset 清空上下文
"""

import os
import sys

import anthropic
from dotenv import load_dotenv

# override=True：你 shell 里可能已经有 ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL
# （指向 Anthropic 官方），本项目要用 .env 里的中转站配置，必须覆盖掉。
load_dotenv(override=True)

from tools import local, xhs_mcp  # noqa: E402  (必须在 load_dotenv 之后导入)

# API key 和 base_url 由 SDK 直接读环境变量（ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL），
# 见 .env。只有模型名需要自己取。
MODEL = os.getenv("AGENT_MODEL", "deepseek-v4-flash")
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "8000"))
SHOW_THINKING = os.getenv("SHOW_THINKING", "0") == "1"
MAX_TOOL_ROUNDS = int(os.getenv("MAX_TOOL_ROUNDS", "12"))

BASE_SYSTEM = """你是一个小红书内容助手，擅长选题、标题、正文和话题标签。
回答简洁、口语化，不要写多余的客套话。

重要：小红书不渲染 markdown，绝对不要用 #、##、**、``` 这类语法。
需要强调就用 emoji 或者换行分段，标题直接写文字。

工作方式：
- 动笔写之前，先用 read_skill 读对应的写作 skill，按它的规范写
- 写自有产品的帖子，先用 read_product 读产品档案，不要凭印象编造
- 要配图时先读 image-视觉规范，按里面的固定后缀拼 prompt，再调 generate_image
- 稿子给用户看过、用户确认满意之后，才调 save_note 存稿"""

DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


def build_system() -> str:
    """把 skill / 产品索引拼进 system prompt。

    索引短且稳定，放 system prompt 比做成 list_skills 工具省一次往返，
    也更容易命中 prompt cache。全文才按需用 read_skill 拉。
    """
    parts = [BASE_SYSTEM]

    skills = local.skill_index()
    if skills:
        lines = "\n".join(f"- {n}：{d}" for n, d in skills)
        parts.append(f"可用的 skill（用 read_skill 读全文）：\n{lines}")

    products = local.product_index()
    if products:
        lines = "\n".join(f"- {n}：{d}" for n, d in products)
        parts.append(f"自有产品档案（用 read_product 读全文）：\n{lines}")

    return "\n\n".join(parts)


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

    # ------------------------------------------------------------ 单次请求

    def _stream_once(self):
        """发一次请求并流式打印。返回 final message；额度耗尽返回 None。"""
        in_thinking = False
        thinking_chars = 0

        with self.client.messages.stream(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=self.system,
            tools=self.tools,
            # 让思考过程可见，否则终端会干等一段没有输出。
            # DeepSeek 走中转站时这个参数是 no-op（它本来就返回 thinking block），
            # 换回 claude-opus-5 时才真正生效。
            thinking={"type": "adaptive", "display": "summarized"},
            messages=self.messages,
        ) as stream:
            for event in stream:
                if event.type == "content_block_start":
                    if event.content_block.type == "thinking":
                        in_thinking = True
                        print(f"{DIM}[思考中", end="", flush=True)
                    elif event.content_block.type == "text" and in_thinking:
                        print(f"]{RESET}\n")
                        in_thinking = False
                elif event.type == "content_block_delta":
                    if event.delta.type == "thinking_delta":
                        # DeepSeek 返回的是完整原始思维链，很长。默认只打点表示进度，
                        # 想看全文在 .env 里设 SHOW_THINKING=1。
                        if SHOW_THINKING:
                            print(event.delta.thinking, end="", flush=True)
                        else:
                            thinking_chars += len(event.delta.thinking)
                            if thinking_chars >= 80:
                                thinking_chars = 0
                                print(".", end="", flush=True)
                    elif event.delta.type == "text_delta":
                        print(event.delta.text, end="", flush=True)

            final = stream.get_final_message()

        if in_thinking:
            print(f"]{RESET}")

        text = "".join(b.text for b in final.content if b.type == "text")

        # max_tokens 是思考和正文共用的额度。推理模型可能把额度全烧在思考上，
        # 结果 content 里只有 thinking 没有 text——不报错，但一个字都没输出。
        if final.stop_reason == "max_tokens" and not text.strip() \
                and not any(b.type == "tool_use" for b in final.content):
            print(f"\n{DIM}模型把 {MAX_TOKENS} tokens 全用在思考上了，没有输出正文。\n"
                  f"可以简化问题重问，或调大 .env 里的 MAX_TOKENS。{RESET}\n")
            return None

        if final.stop_reason == "max_tokens":
            print(f"\n{DIM}（回答在 {MAX_TOKENS} tokens 处被截断）{RESET}")

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
            # 工具报错要作为 tool_result 回给模型，让它自己决定换个方式，
            # 而不是把整个对话崩掉。
            return f"工具执行出错: {type(e).__name__}: {e}"

    # ------------------------------------------------------------ 主流程

    def chat(self, user_input: str) -> None:
        self.messages.append({"role": "user", "content": user_input})
        rollback_to = len(self.messages) - 1

        for _ in range(MAX_TOOL_ROUNDS):
            final = self._stream_once()
            if final is None:
                del self.messages[rollback_to:]  # 这轮死了，回滚干净
                return

            # 存整个 content：thinking 和 tool_use block 都要原样带回下一轮。
            self.messages.append({"role": "assistant", "content": final.content})

            if final.stop_reason != "tool_use":
                print("\n")
                return

            results = []
            for block in final.content:
                if block.type != "tool_use":
                    continue
                brief = ", ".join(f"{k}={str(v)[:40]}" for k, v in block.input.items())
                print(f"\n{DIM}⚙ {block.name}({brief}){RESET}", flush=True)
                out = self._dispatch(block.name, dict(block.input))
                print(f"{DIM}  ← {out.splitlines()[0][:100] if out else '(空)'}{RESET}\n",
                      flush=True)
                results.append({
                    "type": "tool_result", "tool_use_id": block.id, "content": out,
                })

            # 一条 user 消息里放回全部 tool_result，不要拆成多条。
            self.messages.append({"role": "user", "content": results})

        print(f"\n{DIM}工具调用超过 {MAX_TOOL_ROUNDS} 轮，停下了。{RESET}\n")


def main() -> int:
    mcp_tools, mcp_note = xhs_mcp.load()
    tools = local.TOOLS + mcp_tools

    agent = Agent(client=anthropic.Anthropic(), tools=tools)

    print(f"{BOLD}小红书 Agent{RESET}  {DIM}[{MODEL}]{RESET}"
          f"  —  exit/quit 退出，/reset 清空上下文")
    print(f"{DIM}工具 {len(tools)} 个：{', '.join(t['name'] for t in tools)}{RESET}")
    print(f"{DIM}{mcp_note}{RESET}\n")

    while True:
        try:
            user_input = input(f"{BOLD}你 ›{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见。")
            return 0

        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit"}:
            print("再见。")
            return 0
        if user_input == "/reset":
            agent.reset()
            print(f"{DIM}上下文已清空。{RESET}\n")
            continue

        print(f"\n{BOLD}助手 ›{RESET} ", end="", flush=True)
        try:
            agent.chat(user_input)
        except anthropic.AuthenticationError:
            print("\nAPI key 无效，检查 ANTHROPIC_API_KEY。")
            return 1
        except anthropic.RateLimitError:
            print("\n触发限流，等一会儿再试。")
            agent.messages.pop()
        except anthropic.APIStatusError as e:
            print(f"\nAPI 报错 {e.status_code}: {e.message}")
            agent.messages.pop()
        except anthropic.APIConnectionError:
            print("\n网络连不上，检查一下网络。")
            agent.messages.pop()


if __name__ == "__main__":
    sys.exit(main())
