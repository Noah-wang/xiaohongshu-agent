import sys, pathlib, types
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import discord_bot as D

class FakeTag:
    def __init__(self, name): self.name = name
class FakeThread:
    def __init__(self, names): self.applied_tags = [FakeTag(n) for n in names]

def hint(names): return D.tag_hint(FakeThread(names))

print("=== 你实际建的两个标签 ===")
h = hint(["高驰agent"]); print(h)
assert "coros-running-agent" in h and "read_product" in h
assert "xhs-product-promo" in h, "产品标签应带默认写法"

h = hint(["飞书Mark"]); print("\n" + h)
assert "feishu-mark-agent" in h

print("\n=== 产品 + 写法组合 ===")
h = hint(["高驰agent", "干货"]); print(h)
assert "coros-running-agent" in h and "xhs-howto" in h
assert "默认按 xhs-product-promo" not in h, "已指定写法就不该再给默认"

print("\n=== 直接用 skill/产品原名当标签 ===")
h = hint(["xhs-de-ai"]); print(h); assert "xhs-de-ai" in h
h = hint(["feishu-mark-agent"]); print(h); assert "feishu-mark-agent" in h

print("\n=== 无标签 / 未知标签 ===")
assert hint([]) == ""
assert hint(["随便写的"]) == ""

print("\n全部通过 ✅")
