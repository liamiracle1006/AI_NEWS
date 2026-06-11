# Skill: remind

## 简介

单次定时提醒。用户用自然语言说"几时几分干啥"，bot 落库 → 到点用微信推送回去。

## 触发词

- `提醒我`
- `提醒一下`
- `提醒`
- `remind me` / `remind`
- `查提醒` / `列提醒` / `我的提醒`（列出未触发的）
- `取消提醒 #N`（撤掉某条）

## 输入 → 输出

| 用户发 | bot 回 | 后续 |
|---|---|---|
| `提醒我 30 分钟后看锅` | `好，30 分钟后提醒你：『看锅』。` | 30 分钟后微信收到提醒 |
| `提醒我明天 8 点开会` | `好，X 小时后提醒你：『开会』。` | 明天 8 点收到 |
| `查提醒` | 列出未触发的 | — |
| `取消提醒 #3` | `撤了。` | — |

## 工作流

1. handler 把用户消息丢给 DeepSeek 解析时间 + 抽 message
2. 解析失败 → 提示用户再说一次（"时间没听懂，能具体点吗？"）
3. 解析成功 → `routing_log.add_reminder(user_id, ts_due, message)` 落 SQLite
4. `wechat/scheduler.py` 的 `_remind_loop()` 每 30 秒扫一次到期未触发的，调 `channel.send_text` 推送

## 安全边界

- 时间 ts_due 必须未来（过去时间拒绝）
- message ≤ 120 字
- 没鉴权但只发给原 user_id（推送目标 = 创建提醒的人）
- LLM 解析失败时优雅降级，不抛异常

## 给 @claude 的提示

修改这个工具时注意：
- `_PARSER_SYSTEM` 改了要重新 smoke test 几条经典输入（30 分钟后 / 明天 8 点 / 晚上 10 点）
- `routing_log.reminders` 表的 schema 在 `wechat/routing_log.py:_ensure_schema`
- scheduler 循环在 `wechat/scheduler.py:_remind_loop`，改提醒频率要同步改那里
