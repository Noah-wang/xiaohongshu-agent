# xiaohongshu-agent

最基础的对话式 agent loop，命令行里跟 Claude 多轮对话。

## 快速开始

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # 填入你的 ANTHROPIC_API_KEY
python agent.py
```

## 它是什么

`agent.py` 里的 `Agent` 类做三件事：

1. 把每轮 user 输入 append 进 `self.messages`
2. 带上完整历史调用 Messages API（流式）
3. 把返回的 `content` 整个 append 回历史

Claude API 是无状态的，"记忆"就是这份本地的 `messages` 列表。

## 几个实现细节

- **存 `final.content` 而不是纯文本**：thinking block 需要原样带回下一轮，只存字符串会丢掉。
- **`display: "summarized"`**：Opus 5 默认思考但不返回摘要，终端会干等一段没输出。打开摘要后能看到进度。
- **模型是 `claude-opus-5`**，1M 上下文。想省钱可以换 `claude-sonnet-5`。

## 下一步能加什么

- 工具调用：在 `messages.stream()` 里加 `tools=`，然后处理 `stop_reason == "tool_use"`
- 上下文太长：加 compaction（`context_management`）
- 换成 SDK 的 tool runner（`client.beta.messages.tool_runner`），不用自己写工具循环

## 部署与开发位置

线上跑在腾讯云 `43.134.186.150`，路径 `~/noahwang_agents/xiaohongshu-agent`，
和 `coros-running-agent`、`feishu-mark-agent` 并列在同一个目录下。

**开发在服务器上做**，通过写权限 deploy key 推回 GitHub：

```bash
ssh ubuntu@43.134.186.150
cd ~/noahwang_agents/xiaohongshu-agent
# 改完
git add -A && git commit -m "..." && git push
```

本地仓库 `git pull` 即可同步。两边不要同时改，以免分叉。

`.env` 不在版本控制里，服务器和本地各有一份，改配置要分别改。
