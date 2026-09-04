"""Token 用量与花费统计。

两个来源，可信度不同：

1. **token 数**——来自每次响应的 usage 字段，精确。
2. **花费**——优先用中转站的累计消费接口做差值，那是真实扣费；
   接口不可用时才退回本地价格表估算，估算值一定标注出来。

价格表是上游官方价，中转站实际计费未必一致，所以只当兜底。
"""

import json
import os
import threading
import time
import urllib.error
import urllib.request

# 上游官方价（美元 / 每百万 token），仅用于接口不可用时的兜底估算。
# 中转站按自己的费率结算，数字对不上很正常。
PRICES = {
    "deepseek-v4-flash": (0.28, 0.42),
    "deepseek-v4-pro": (0.55, 2.19),
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "glm-5.3": (0.60, 2.20),
}
DEFAULT_PRICE = (0.5, 2.0)

_lock = threading.Lock()
_state = {
    "started": time.time(),
    "calls": 0,
    "by_model": {},          # model -> {in, out, cache_read, cache_write, calls}
    "spend_start": None,     # 会话开始时中转站的累计消费
}


# ---------------------------------------------------------------- 采集

def record(model: str, usage) -> None:
    """每次 API 响应后调用。usage 是 SDK 的 usage 对象或 dict。"""
    def g(k):
        v = usage.get(k) if isinstance(usage, dict) else getattr(usage, k, None)
        return v or 0

    with _lock:
        _state["calls"] += 1
        m = _state["by_model"].setdefault(
            model, {"in": 0, "out": 0, "cache_read": 0, "cache_write": 0, "calls": 0})
        m["calls"] += 1
        m["in"] += g("input_tokens")
        m["out"] += g("output_tokens")
        m["cache_read"] += g("cache_read_input_tokens")
        m["cache_write"] += g("cache_creation_input_tokens")


def reset() -> None:
    with _lock:
        _state.update(started=time.time(), calls=0, by_model={}, spend_start=None)


# ---------------------------------------------------------------- 中转站真实消费

def _fetch_spend() -> float | None:
    """中转站的累计消费。接口忽略日期参数，返回的是账号总额，靠差值算本次会话。"""
    base = os.getenv("ANTHROPIC_BASE_URL", "").rstrip("/")
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not base or not key:
        return None
    url = f"{base}/v1/dashboard/billing/usage?start_date=2020-01-01&end_date=2035-01-01"
    try:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
        return float(json.load(urllib.request.urlopen(req, timeout=15))["total_usage"])
    except Exception:
        return None


def mark_start() -> None:
    """会话开始时记一次基线，之后才能算出这次花了多少。"""
    with _lock:
        if _state["spend_start"] is None:
            _state["spend_start"] = _fetch_spend()


# ---------------------------------------------------------------- 报告

def _estimate(model: str, d: dict) -> float:
    pin, pout = PRICES.get(model, DEFAULT_PRICE)
    # 缓存读按输入价的 1/10 估，写按 1.25 倍——通用惯例，不是中转站的实际规则
    return ((d["in"] + d["cache_write"] * 1.25 + d["cache_read"] * 0.1) * pin
            + d["out"] * pout) / 1_000_000


def report() -> str:
    with _lock:
        snap = json.loads(json.dumps(_state))

    if not snap["by_model"]:
        return "本次会话还没有产生任何调用。"

    mins = (time.time() - snap["started"]) / 60
    lines = [f"本次会话 {mins:.0f} 分钟，共 {snap['calls']} 次调用"]

    tin = tout = tcr = 0
    est = 0.0
    for m, d in sorted(snap["by_model"].items(), key=lambda x: -x[1]["out"]):
        tin += d["in"]; tout += d["out"]; tcr += d["cache_read"]
        est += _estimate(m, d)
        cache = f"，缓存命中 {d['cache_read']:,}" if d["cache_read"] else ""
        lines.append(f"  {m}：{d['calls']} 次｜输入 {d['in']:,}｜输出 {d['out']:,}{cache}")

    lines.append(f"合计：输入 {tin:,} + 输出 {tout:,} = {tin + tout:,} tokens"
                 + (f"（其中 {tcr:,} 走了缓存）" if tcr else ""))

    now = _fetch_spend()
    start = snap["spend_start"]
    if now is not None and start is not None:
        lines.append(f"中转站实际扣费：本次会话 {now - start:.4f}，账号累计 {now:.2f}"
                     f"（单位以中转站后台为准，本工具不换算成美元）")
    elif now is not None:
        lines.append(f"中转站账号累计扣费：{now:.2f}（本次会话起点未记录，算不出增量）")
    else:
        lines.append("中转站计费接口读不到，只能给估算值。")

    lines.append(f"按上游官方价估算：约 ${est:.4f}"
                 f"（仅供参考，中转站按自己的费率结算）")
    return "\n".join(lines)


def current_model() -> str:
    return os.getenv("AGENT_MODEL", "deepseek-v4-flash")
