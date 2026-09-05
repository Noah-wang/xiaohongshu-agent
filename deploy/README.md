# 部署

线上：腾讯云 `43.134.186.150`，`~/noahwang_agents/xiaohongshu-agent`

## 首次部署

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # 然后填 key
sudo cp deploy/xiaohongshu-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now xiaohongshu-agent
```

## 日常

```bash
git pull && sudo systemctl restart xiaohongshu-agent   # 更新代码后
sudo journalctl -u xiaohongshu-agent -f                # 看日志
systemctl status xiaohongshu-agent                     # 看状态
```

## 注意

- **同一个 Discord token 只能有一个进程在跑**。本地调试前先
  `sudo systemctl stop xiaohongshu-agent`，否则两个 bot 会各回一遍。
- `.env` 不在版本控制里，服务器和本地各一份，改配置要分别改。
- service 里的 `python -u` 不能去掉，否则日志被缓冲，journalctl 里什么都看不到。

## 小红书 MCP

同机部署在 `~/noahwang_agents/xiaohongshu-mcp`，服务 `xiaohongshu-mcp.service`，
监听 18060（云防火墙挡了公网，且 AUTH_TOKEN 强制鉴权，无 token 返回 401）。

只放行 4 个只读工具（search_feeds / get_feed_detail / list_feeds / user_profile），
发布、评论、点赞等 14 个写操作在 `tools/xhs_mcp.py` 的白名单里被拦掉。

### 部署时踩的三个坑

1. **内置 Chrome 148 在这台机器上 segfault**，装全依赖也没用。解法是装
   `google-chrome-stable`，再把内置的 `chrome` 换成转发脚本
   （原文件备份为 `chrome.orig`）。`-rod bin=` 参数不生效，wrapper 自己管路径。
2. **登录工具是有头模式**，报 `Missing X server`。用 Xvfb 建虚拟显示 `:99`，
   service 里 `ExecStartPre` 会确保 Xvfb 在跑。
3. **首次扫码会触发短信验证**（机房 IP 风控）。需要人工操作：
   `x11vnc -display :99 -localhost` + SSH 隧道 `-L 5900:localhost:5900`，
   用屏幕共享连上去自己输验证码。cookie 存在 `cookies.json`，之后复用。

### 重新登录

```bash
cd ~/noahwang_agents/xiaohongshu-mcp
sudo systemctl stop xiaohongshu-mcp
DISPLAY=:99 ./xiaohongshu-login-linux-amd64
# 另开终端截图看二维码：DISPLAY=:99 import -window root /tmp/qr.png
sudo systemctl start xiaohongshu-mcp
```
