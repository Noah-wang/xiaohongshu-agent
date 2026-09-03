import sys, builtins
import pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import agent as A

def feed(lines):
    it = iter(lines)
    def _in(*a):
        try: return next(it)
        except StopIteration: raise EOFError
    builtins.input = _in

print("=== /paste 正常结束（含空行）===")
feed(["第一行", "第二行", "", "第四行", "."])
r = A.read_multiline(); print(repr(r))
assert r == "第一行\n第二行\n\n第四行", "拼接错误"

print("=== /paste 取消 ===")
feed(["随便写点", "/cancel"])
r = A.read_multiline(); print(repr(r)); assert r == ""

print("=== /paste 遇 EOF 也收尾 ===")
feed(["只有一行"])
r = A.read_multiline(); print(repr(r)); assert r == "只有一行"

print("=== /file 正常 ===")
r = A.read_file_prompt("skills/xhs-de-ai/references/zh-vocab.md 去AI味")
assert r.startswith("去AI味") and "连接套话" in r, "文件内容没带上"
print(f"  长度 {len(r)}，开头: {r[:20]!r}")

print("=== /file 不存在 ===")
r = A.read_file_prompt("nope.md"); print(repr(r)); assert r == ""

print("=== /file 空参数 ===")
r = A.read_file_prompt(""); print(repr(r)); assert r == ""

print("\n全部通过 ✅")
