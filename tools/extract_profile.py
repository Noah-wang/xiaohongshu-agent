"""从 GitHub 仓库提炼小红书发帖档案，写进 products/。

    python tools/extract_profile.py Noah-wang/feishu-mark-agent

只喂 README 出来的档案太干（缺功能细节、缺更新记录），所以会一并读 docs/ 下的
文档和 README 的更新段落。

提炼用 claude-opus-5，不用 .env 里的 AGENT_MODEL：写文案和结构化提炼是两种活。
另外注意 prompt 里不要写「信息不足就标未覆盖、不要编造」这类自我审查规则——
实测会让推理模型对每个字段反复权衡，思考量涨 8 倍甚至把 max_tokens 烧光。
护栏放在最后一句话，不要逐字段施加。
"""

import base64
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=True)
import os  # noqa: E402

# 提炼是结构化任务，用比写文案更强的档位。本来默认 claude-opus-5，
# 但中转站上游 Claude 账号池经常空（503 "no active Kiro accounts available"），
# 所以默认退到 deepseek-v4-pro。Claude 可用时用 EXTRACT_MODEL 切回去。
MODEL = os.getenv("EXTRACT_MODEL", "deepseek-v4-pro")
MAX_DOC_CHARS = 60000

TEMPLATE = """---
name: <仓库名>
repo: <仓库地址>
一句话: <定位，不超过 40 字>
---

## 面向谁
## 解决的痛点
## Before / After
## 核心功能
每条要具体到能单独当一个帖子的卖点，不要写"功能丰富"这种。
## 典型使用片段
真实的「用户说什么 → 它做什么」例子，2-3 个。
## 上手门槛
技术栈、依赖、要自己准备什么。
## 已知短板
发"踩坑""劝退"类帖子全靠这段，尽量挖满。
## 更新记录
按时间倒序，每条一句话。
## 可发的帖子选题
基于以上信息，列 3-5 个具体的小红书选题方向。"""


def gh(path: str) -> str:
    r = subprocess.run(["gh", "api", path, "--jq", ".content"],
                       capture_output=True, text=True)
    if r.returncode or not r.stdout.strip():
        return ""
    try:
        return base64.b64decode(r.stdout.strip()).decode("utf-8", "replace")
    except Exception:
        return ""


def collect(repo: str) -> str:
    """README + docs/ 下的 markdown，按体量截断。"""
    r = subprocess.run(
        ["gh", "api", f"repos/{repo}/git/trees/HEAD?recursive=1",
         "--jq", '.tree[] | select(.type=="blob") | .path'],
        capture_output=True, text=True)
    paths = [p for p in r.stdout.splitlines() if p.endswith(".md")]

    # README 优先，然后 docs/ 下的架构与设计文档，跳过第三方 skill 和英文副本
    picked = [p for p in paths if p.lower() == "readme.md"]
    picked += [p for p in sorted(paths)
               if p.startswith("docs/") and ".en." not in p
               and "/skills/" not in p][:6]

    parts, total = [], 0
    for p in picked:
        body = gh(f"repos/{repo}/contents/{p}")
        if not body:
            continue
        body = body[:20000]
        if total + len(body) > MAX_DOC_CHARS:
            break
        total += len(body)
        parts.append(f"===== 文件: {p} =====\n{body}")
    print(f"  读取 {len(parts)} 个文档，共 {total} 字符")
    return "\n\n".join(parts)


def extract(repo: str, docs: str) -> str:
    prompt = (
        f"下面是开源项目 {repo} 的 README 和文档。请提炼成一份「小红书发帖档案」，"
        f"严格按这个结构输出，可以合理推断：\n\n{TEMPLATE}\n\n"
        f"写作要求：面向内容创作者，不是开发者——少用技术名词，多写用户能感知的东西。"
        f"具体的数字、命令、版本号照抄原文，不要自己造。\n\n"
        f"项目文档：\n{docs}"
    )
    # 档案字段多、要写具体，8000 会被截断；推理模型还要额外吃掉一部分额度
    body = json.dumps({"model": MODEL, "max_tokens": 30000,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request(
        os.getenv("ANTHROPIC_BASE_URL").rstrip("/") + "/v1/messages", data=body,
        headers={"x-api-key": os.getenv("ANTHROPIC_API_KEY"),
                 "anthropic-version": "2023-06-01", "Content-Type": "application/json"})
    # 中转站经常 503（system cpu overloaded），退避重试
    last = None
    for attempt in range(5):
        try:
            d = json.load(urllib.request.urlopen(req, timeout=600))
            break
        except urllib.error.HTTPError as e:
            last = e
            if e.code not in (429, 500, 502, 503, 504):
                raise
            wait = 8 * (attempt + 1)
            print(f"  {e.code}，{wait}s 后重试（{attempt + 1}/5）")
            time.sleep(wait)
    else:
        raise last

    if d.get("stop_reason") == "max_tokens":
        print("  ⚠ 输出被 max_tokens 截断")
    return "".join(b.get("text", "") for b in d["content"] if b["type"] == "text")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    repo = sys.argv[1].removeprefix("https://github.com/").removesuffix(".git")
    name = repo.split("/")[-1]

    print(f"[{repo}]")
    docs = collect(repo)
    if not docs:
        print("  ❌ 一个文档都没读到")
        return 1

    text = extract(repo, docs).strip()
    if not text.startswith("---"):
        text = f"---\nname: {name}\nrepo: https://github.com/{repo}\n---\n\n{text}"

    out = ROOT / "products" / f"{name}.md"
    out.write_text(text + "\n", encoding="utf-8")
    print(f"  ✅ 写入 {out.relative_to(ROOT)}（{len(text)} 字符）")
    print("  ⚠ 这是模型从文档推的，发帖前请人工校对事实性内容")
    return 0


if __name__ == "__main__":
    sys.exit(main())
