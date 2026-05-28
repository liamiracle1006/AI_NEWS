# AI_NEWS 微信插件

> **此目录是插件的唯一源代码位置。** CoW 项目下的 `plugins/ai_news/` 是它的副本，
> 由 `sync_to_cow.ps1` 同步过去，不参与版本控制。

## 用途

通过 chatgpt-on-wechat (CoW) 把 AI_NEWS 接入微信（或 CoW 自带的 terminal 渠道用于本地测试）。
提供：被动查询（分析国家/话题）、热度榜、单国文章、定时推送、热点告警、图片化输出。

## 文件结构

```
wechat_plugin/
├── __init__.py             导出 AINews 插件类
├── ai_news.py              主插件：消息监听 + API 调用
├── intent_parser.py        自然语言 → 结构化意图
├── formatter.py            JSON 结果 → 微信文本 / Pillow 图卡
├── scheduler.py            每日推送 + 突发热点告警（threading）
├── config.json.template    插件配置模板（白名单、定时表、API 地址）
├── README.md               本文件
└── sync_to_cow.ps1         一键同步到 CoW 项目
```

## 使用步骤

### 1. 在 CoW 上跑（验证模式：terminal 渠道，无需微信）

确保 CoW 已克隆到 `c:/Users/wangzy/Desktop/hobby/chatgpt-on-wechat/`，然后：

```powershell
# 同步本目录到 CoW 的 plugins/ai_news/
.\sync_to_cow.ps1

# 第一次使用：把模板复制为 config.json（之后修改 config.json 不再覆盖）
cd c:\Users\wangzy\Desktop\hobby\chatgpt-on-wechat\plugins\ai_news
copy config.json.template config.json
```

确认 CoW 主配置 `chatgpt-on-wechat/config.json`：
- `channel_type`: `"terminal"`（命令行验证）或 `"weixin"`（接真实微信）
- `deepseek_api_key`: 你的 DeepSeek key

启动：
```bash
# 终端 1
cd c:\Users\wangzy\Desktop\hobby\AI_NEWS
uvicorn api.main:app --port 8000

# 终端 2
cd c:\Users\wangzy\Desktop\hobby\chatgpt-on-wechat
python app.py
```

### 2. 修改插件代码

**只改这里**（`AI_NEWS/wechat_plugin/`），改完跑 `.\sync_to_cow.ps1` 同步到 CoW，重启 `python app.py`。
不要直接改 CoW 下的副本——下次同步会被覆盖。

## 指令一览

| 输入 | 行为 |
|---|---|
| `分析以色列` | 当日深度分析 |
| `加沙本周分析` / `本周加沙` | 7 天叙事分析 |
| `分析以色列 图片` | PNG 图卡输出 |
| `今日热点` / `热度榜` | 全球新闻热度榜 Top 15 |
| `中国新闻` | 单国文章标题列表 |
| `历史简报` | briefs 列表 |
| `帮助` / `help` | 速查 |
| 其他文本 | CoW 默认 LLM 闲聊 |

## 已知占位

`scheduler.py` 的 `send_to_user()` 是占位实现（CoW 不同 channel 主动发送接口不一致）。
被动查询完全可用；定时推送/告警目前只写日志。

## 风险提示

- iLink bot 协议虽然走腾讯官方域名，仍不建议绑日常主号
- 单聊低频自用风险很低，但**严禁群发、自动加好友、高频回复**
