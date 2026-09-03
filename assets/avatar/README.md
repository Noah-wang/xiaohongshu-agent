# bot-avatar.png

Discord bot「小红书Agent」的头像。1254×1254 PNG。

用 [ip-as-logo](https://github.com/s1dashu/ip-as-logo-skill) skill 生成，从 12 张候选里选定
（3 个非红薯方向 × 2 + 3 种红薯处理 × 2）。

## 生成参数

| 项 | 值 |
|---|---|
| 模型 | `gpt-image-2`（走中转站 `/v1/images/generations`） |
| 请求尺寸 | 1536×1536（服务实际返回 1254×1254，未重采样） |
| 约束方式 | 主提示词内的 `Constraints:` 行，无独立 negative 参数 |
| 主体 | 红薯，半剖处理——红皮 + 一大块内瓤 |
| IP 色 1 | bright true red |
| IP 色 2 | warm amber orange |
| 背景色 | cream beige |
| 构图 | 从左下角探出，占画面 75–85% |

## 为什么是这张

内瓤是一块连续的大色域，缩到 32×32 仍然成立。另外几版的识别特征（两端截面、
头顶叶子）在缩略图或圆形裁切下会丢失。

## 换头像

开发者后台 → Application → Bot → 点头像上传本文件。这步只能手动做。
