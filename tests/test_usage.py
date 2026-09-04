import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from tools import usage

usage.reset()
print("=== 无调用 ===")
print(" ", usage.report())
assert "还没有产生任何调用" in usage.report()

print("\n=== 记两次 deepseek + 一次 opus ===")
usage.record("deepseek-v4-flash", {"input_tokens":1200,"output_tokens":800,
                                   "cache_read_input_tokens":400,"cache_creation_input_tokens":0})
usage.record("deepseek-v4-flash", {"input_tokens":3000,"output_tokens":1500,
                                   "cache_read_input_tokens":2800,"cache_creation_input_tokens":0})
usage.record("claude-opus-5", {"input_tokens":500,"output_tokens":2000,
                               "cache_read_input_tokens":0,"cache_creation_input_tokens":0})
r = usage.report()
print(r)
assert "3 次调用" in r
assert "deepseek-v4-flash：2 次" in r
assert "输入 4,200" in r and "输出 2,300" in r, "合计应为 4200/2300"
assert "3,200" in r, "缓存命中合计应为 3200"
assert "$" in r, "应给出估算金额"

print("\n=== SDK usage 对象（非 dict）也要认 ===")
usage.reset()
class U:
    input_tokens=100; output_tokens=50
    cache_read_input_tokens=None; cache_creation_input_tokens=None
usage.record("x-model", U())
r=usage.report(); print(" ", r.splitlines()[1])
assert "输入 100" in r

print("\n全部通过 ✅")
