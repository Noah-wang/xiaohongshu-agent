"""本地工具：读 skill、读产品档案、生成配图、存稿。

每个工具两部分——给模型看的 schema（TOOLS）和实际执行的函数（HANDLERS）。
加一个工具 = TOOLS 加一条 + HANDLERS 加一行，主循环不用动。
"""

import datetime
import json
import os
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = ROOT / "skills"
PRODUCTS_DIR = ROOT / "products"
OUTPUT_DIR = ROOT / "output"

IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gpt-image-2")
# gpt-image-2 只接受固定几档尺寸，竖版就是 1024x1536（2:3）。
# 改这里的话记得同步改 skills/image-视觉规范/SKILL.md 里的比例，别让规范和实际打架。
IMAGE_SIZE = os.getenv("IMAGE_SIZE", "1024x1536")


# ---------------------------------------------------------------- 索引

def _frontmatter(path: Path) -> dict:
    """读 markdown 顶部 --- 之间的键值对。只做最简解析，够用就行。"""
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---", text, re.S)
    if not m:
        return {}
    out = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def skill_index() -> list[tuple[str, str]]:
    """[(name, description), ...]，放进 system prompt 供模型挑选。"""
    items = []
    for p in sorted(SKILLS_DIR.glob("*/SKILL.md")):
        fm = _frontmatter(p)
        items.append((fm.get("name", p.parent.name), fm.get("description", "")))
    return items


def product_index() -> list[tuple[str, str]]:
    items = []
    for p in sorted(PRODUCTS_DIR.glob("*.md")):
        if p.name == "INDEX.md":
            continue
        fm = _frontmatter(p)
        items.append((fm.get("name", p.stem), fm.get("一句话", "")))
    return items


# ---------------------------------------------------------------- 工具实现

def _safe_name(name: str) -> str:
    """挡掉 ../ 之类的路径穿越。名字里只允许中英文、数字、连字符、下划线。"""
    if not re.fullmatch(r"[\w一-鿿-]+", name or ""):
        raise ValueError(f"非法名称: {name!r}")
    return name


def read_skill(name: str) -> str:
    path = SKILLS_DIR / _safe_name(name) / "SKILL.md"
    if not path.exists():
        avail = ", ".join(n for n, _ in skill_index())
        return f"没有叫 {name} 的 skill。现有：{avail}"
    return path.read_text(encoding="utf-8")


def read_product(name: str) -> str:
    path = PRODUCTS_DIR / f"{_safe_name(name)}.md"
    if not path.exists():
        avail = ", ".join(n for n, _ in product_index())
        return f"没有叫 {name} 的产品档案。现有：{avail}"
    return path.read_text(encoding="utf-8")


def generate_image(prompt: str) -> str:
    """走 /v1/images/generations——和对话的 /v1/messages 不是同一个 endpoint。"""
    base = os.getenv("ANTHROPIC_BASE_URL", "").rstrip("/")
    key = os.getenv("ANTHROPIC_API_KEY", "")
    body = json.dumps({
        "model": IMAGE_MODEL, "prompt": prompt, "n": 1, "size": IMAGE_SIZE,
    }).encode()
    req = urllib.request.Request(
        f"{base}/v1/images/generations", data=body,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        d = json.load(urllib.request.urlopen(req, timeout=300))
    except Exception as e:
        return f"出图失败: {e}"
    if "error" in d:
        return f"出图失败: {d['error'].get('message', d['error'])}"
    return d["data"][0].get("url") or "(返回里没有 url)"


def save_note(title: str, body: str, image_url: str = "") -> str:
    """存稿。图片一并下载到本地——将来 MCP 发布需要的是本地文件路径，不是 URL。"""
    OUTPUT_DIR.mkdir(exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = re.sub(r"[^\w一-鿿-]+", "", title)[:24] or "note"
    note_path = OUTPUT_DIR / f"{stamp}-{slug}.md"

    saved_img = ""
    if image_url.startswith("http"):
        img_dir = OUTPUT_DIR / "images"
        img_dir.mkdir(exist_ok=True)
        img_path = img_dir / f"{stamp}-{slug}.png"
        try:
            urllib.request.urlretrieve(image_url, img_path)
            saved_img = str(img_path.relative_to(ROOT))
        except Exception as e:
            saved_img = f"(下载失败: {e})"

    note_path.write_text(
        f"# {title}\n\n{body}\n\n---\n配图: {saved_img or image_url or '无'}\n",
        encoding="utf-8")
    rel = note_path.relative_to(ROOT)
    return f"已存到 {rel}" + (f"，配图 {saved_img}" if saved_img else "")


# ---------------------------------------------------------------- 注册表

TOOLS = [
    {
        "name": "read_skill",
        "description": "读取一个写作或配图 skill 的完整规范。动笔之前必须先读对应的 skill——"
                       "skill 里定义了这类内容的结构、语气、排版和禁忌。可用的 skill 见系统提示里的列表。",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "skill 名称"}},
            "required": ["name"],
        },
    },
    {
        "name": "read_product",
        "description": "读取某个自有产品的档案，包含定位、目标用户、痛点、使用场景和已知短板。"
                       "写产品宣传帖之前必须先读，不要凭印象编造产品信息。",
        "input_schema": {
            "type": "object",
            "properties": {"name": {"type": "string", "description": "产品名称"}},
            "required": ["name"],
        },
    },
    {
        "name": "generate_image",
        "description": "根据英文 prompt 生成一张配图，返回图片 URL。"
                       "调用前必须先读 image-视觉规范 skill，并把里面的固定后缀拼在 prompt 末尾，"
                       "否则各篇配图风格会不统一。",
        "input_schema": {
            "type": "object",
            "properties": {"prompt": {"type": "string", "description": "英文图像描述，含固定后缀"}},
            "required": ["prompt"],
        },
    },
    {
        "name": "save_note",
        "description": "把定稿的笔记存到本地 output/ 目录，有配图会一并下载。用户确认满意后再调用。",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "笔记标题"},
                "body": {"type": "string", "description": "正文，含话题标签"},
                "image_url": {"type": "string", "description": "配图 URL，没有就留空"},
            },
            "required": ["title", "body"],
        },
    },
]

HANDLERS = {
    "read_skill": read_skill,
    "read_product": read_product,
    "generate_image": generate_image,
    "save_note": save_note,
}
