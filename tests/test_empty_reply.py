import sys, types
import pathlib; sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import core

class Blk:
    def __init__(s,t,txt=""): s.type=t; s.text=txt
class Msg:
    def __init__(s, blocks, stop): s.content=blocks; s.stop_reason=stop
class Rec(core.Sink):
    def __init__(s): s.notices=[]
    def notice(s,m): s.notices.append(m)

a = core.Agent.__new__(core.Agent)
a.messages=[]; a.client=None; a.model="x"; a.system=""; a.tools=[]

print("=== end_turn 但只有 thinking，没有 text ===")
a.messages=[]
a._stream_once = lambda sink: Msg([Blk("thinking")], "end_turn")
s=Rec(); r=a.chat("测试", s)
print("  返回:", repr(r)); print("  notice:", s.notices)
assert r=="" and len(s.notices)==1 and "没写正文" in s.notices[0], "应该报出原因"

print("\n=== 正常有 text ===")
a.messages=[]
a._stream_once = lambda sink: Msg([Blk("thinking"), Blk("text","正文内容")], "end_turn")
s=Rec(); r=a.chat("测试", s)
print("  返回:", repr(r)); print("  notice:", s.notices)
assert r=="正文内容" and not s.notices, "正常情况不该报"

print("\n=== Discord 空回复的呈现 ===")
import discord_bot as D
lines=["read_skill(name=xhs-de-ai)", "⚠ 模型结束了这一轮却没写正文（stop_reason=end_turn，工具调用 5 轮）。"]
why=[l for l in lines if l.startswith("⚠")]
reply="这轮没有输出。\n"+"\n".join(why)
print("  " + reply.replace("\n","\n  "))
assert D.split_for_discord(reply), "应该能正常切分发送"

print("\n全部通过 ✅")
