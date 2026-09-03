import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from discord_bot import split_for_discord, DISCORD_LIMIT

def check(chunks, original):
    assert all(len(c) <= DISCORD_LIMIT for c in chunks), \
        f"超长: {[len(c) for c in chunks]}"
    joined = "".join(chunks).replace("\n", "").replace(" ", "")
    src = original.replace("\n", "").replace(" ", "")
    assert joined == src, f"内容丢失: {len(joined)} vs {len(src)}"

print("=== 短文本不切 ===")
t = "就一句话"
assert split_for_discord(t) == [t]; print("  ok")

print("=== 空文本 ===")
assert split_for_discord("") == [] and split_for_discord("   ") == []; print("  ok")

print("=== 段落边界优先 ===")
t = ("第一段" * 500) + "\n\n" + ("第二段" * 500)
c = split_for_discord(t); check(c, t)
assert len(c) == 2 and c[0].endswith("第一段") and c[1].startswith("第二段"), \
    f"没切在段落边界: {c[0][-10:]!r} | {c[1][:10]!r}"
print(f"  ok，切成 {len(c)} 段，长度 {[len(x) for x in c]}")

print("=== 无段落时退到句号 ===")
t = "。".join(["这是一个句子" * 30 for _ in range(20)]) + "。"
c = split_for_discord(t); check(c, t)
assert all(x.endswith("。") for x in c[:-1]), "没切在句号"
print(f"  ok，切成 {len(c)} 段")

print("=== 无任何边界也不崩（硬切）===")
t = "啊" * 5000
c = split_for_discord(t); check(c, t)
assert len(c) == 3, f"预期 3 段，实际 {len(c)}"
print(f"  ok，硬切成 {len(c)} 段，长度 {[len(x) for x in c]}")

print("=== 真实小红书长文 ===")
t = "\n\n".join([f"🍁第{i}站：某某路\n梧桐叶黄了一半，走起来很舒服。" * 12 for i in range(1, 9)])
c = split_for_discord(t); check(c, t)
print(f"  ok，{len(t)} 字 → {len(c)} 段，长度 {[len(x) for x in c]}")

print("\n全部通过 ✅")
