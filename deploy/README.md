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
