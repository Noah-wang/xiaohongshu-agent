"""最基础的对话式 Agent Loop。

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

# API key 和 base_url 由 SDK 直接读环境变量（ANTHROPIC_API_KEY / ANTHROPIC_BASE_URL），
# 见 .env。只有模型名需要自己取。
MODEL = os.getenv("AGENT_MODEL", "deepseek-v4-flash")
MAX_TOKENS = 8000
SHOW_THINKING = os.getenv("SHOW_THINKING", "0") == "1"

SYSTEM_PROMPT = """你是一个小红书内容助手，擅长选题、标题、正文和话题标签。
回答简洁、口语化，不要写多余的客套话。

重要：小红书不渲染 markdown，绝对不要用 #、##、**、``` 这类语法。
需要强调就用 emoji 或者换行分段，标题直接写文字。"""

DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


class Agent:
    """一个只会聊天的 agent：维护对话历史，每轮把全量历史发给模型。"""

    def __init__(self, client: anthropic.Anthropic, model: str = MODEL,
                 system: str = SYSTEM_PROMPT):
        self.client = client
        self.model = model
        self.system = system
        self.messages: list[anthropic.types.MessageParam] = []

    def reset(self) -> None:
        self.messages.clear()

    def chat(self, user_input: str) -> None:
        """发一轮消息，边收边打印。"""
        self.messages.append({"role": "user", "content": user_input})

        in_thinking = False
        thinking_chars = 0
        with self.client.messages.stream(
            model=self.model,
            max_tokens=MAX_TOKENS,
            system=self.system,
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
            print(RESET, end="")
        print("\n")

        # 存整个 content（不只是文本）：thinking block 要原样带回下一轮。
        self.messages.append({"role": "assistant", "content": final.content})


def main() -> int:
    agent = Agent(client=anthropic.Anthropic())

    print(f"{BOLD}小红书 Agent{RESET}  {DIM}[{MODEL}]{RESET}"
          f"  —  exit/quit 退出，/reset 清空上下文\n")

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

        print(f"\n{BOLD}Claude ›{RESET} ", end="", flush=True)
        try:
            agent.chat(user_input)
        except anthropic.AuthenticationError:
            print("\nAPI key 无效，检查 ANTHROPIC_API_KEY。")
            return 1
        except anthropic.RateLimitError:
            print("\n触发限流，等一会儿再试。")
            agent.messages.pop()  # 丢掉这条没答上的 user 消息
        except anthropic.APIStatusError as e:
            print(f"\nAPI 报错 {e.status_code}: {e.message}")
            agent.messages.pop()
        except anthropic.APIConnectionError:
            print("\n网络连不上，检查一下网络。")
            agent.messages.pop()


if __name__ == "__main__":
    sys.exit(main())
