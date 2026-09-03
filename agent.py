"""命令行前端。内核在 core.py，Discord 前端在 discord_bot.py。

运行:  python agent.py

命令:
  /paste          多行粘贴，单独一行 . 结束
  /file <路径>    读入文件内容，可附加要求
  /reset          清空上下文
  exit / quit     退出（Ctrl-C 同）
"""

import os
import sys
from pathlib import Path

import anthropic

from core import MAX_TOKENS, MODEL, Agent, Sink, load_tools

SHOW_THINKING = os.getenv("SHOW_THINKING", "0") == "1"

DIM = "\033[2m"
BOLD = "\033[1m"
RESET = "\033[0m"


class ConsoleSink(Sink):
    """终端输出：思维链折叠成进度点，正文流式打印。"""

    def __init__(self):
        self.in_thinking = False
        self.pending = 0

    def thinking(self, delta: str) -> None:
        if not self.in_thinking:
            self.in_thinking = True
            print(f"{DIM}[思考中", end="", flush=True)
        if SHOW_THINKING:
            print(delta, end="", flush=True)
            return
        # DeepSeek 返回的是完整原始思维链，很长。默认只打点表示进度。
        self.pending += len(delta)
        if self.pending >= 80:
            self.pending = 0
            print(".", end="", flush=True)

    def _close_thinking(self) -> None:
        if self.in_thinking:
            self.in_thinking = False
            self.pending = 0
            print(f"]{RESET}\n", flush=True)

    def text(self, delta: str) -> None:
        self._close_thinking()
        print(delta, end="", flush=True)

    def tool_start(self, name: str, args: dict) -> None:
        self._close_thinking()
        brief = ", ".join(f"{k}={str(v)[:40]}" for k, v in args.items())
        print(f"\n{DIM}⚙ {name}({brief}){RESET}", flush=True)

    def tool_done(self, name: str, out: str) -> None:
        head = out.splitlines()[0][:100] if out else "(空)"
        print(f"{DIM}  ← {head}{RESET}\n", flush=True)

    def notice(self, msg: str) -> None:
        self._close_thinking()
        print(f"\n{DIM}{msg}{RESET}\n", flush=True)


def read_multiline() -> str:
    """多行粘贴。终端的 input() 一行一回车，直接粘一整篇稿子会被拆成好几轮对话。"""
    print(f"{DIM}粘贴内容，结束后单独一行输入 .（输入 /cancel 取消）{RESET}")
    lines: list[str] = []
    while True:
        try:
            line = input()
        except (EOFError, KeyboardInterrupt):
            break
        if line.strip() == ".":
            break
        if line.strip() == "/cancel":
            return ""
        lines.append(line)
    return "\n".join(lines).strip()


def read_file_prompt(arg: str) -> str:
    """/file <路径> [附加要求] —— 把文件内容连同要求一起发出去。"""
    if not arg:
        print(f"{DIM}用法：/file <路径> [附加要求]，"
              f"例如 /file output/xxx.md 帮我去下 AI 味{RESET}\n")
        return ""
    parts = arg.split(None, 1)
    path = Path(parts[0]).expanduser()
    instruction = parts[1] if len(parts) > 1 else "看一下这篇稿子"
    if not path.is_file():
        print(f"{DIM}找不到文件：{path}{RESET}\n")
        return ""
    try:
        content = path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"{DIM}读不了 {path}：{e}{RESET}\n")
        return ""
    print(f"{DIM}已读入 {path}（{len(content)} 字符）{RESET}")
    return f"{instruction}\n\n---\n{content}\n---"


def main() -> int:
    tools, mcp_note = load_tools()
    agent = Agent(client=anthropic.Anthropic(), tools=tools)

    print(f"{BOLD}小红书 Agent{RESET}  {DIM}[{MODEL}]{RESET}")
    print(f"{DIM}/paste 粘多行  /file <路径> 读文件  /reset 清空上下文  exit 退出{RESET}")
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
        if user_input == "/paste":
            user_input = read_multiline()
            if not user_input:
                print(f"{DIM}已取消。{RESET}\n")
                continue
        elif user_input.startswith("/file"):
            user_input = read_file_prompt(user_input[5:].strip())
            if not user_input:
                continue

        print(f"\n{BOLD}助手 ›{RESET} ", end="", flush=True)
        try:
            agent.chat(user_input, ConsoleSink())
            print("\n")
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
