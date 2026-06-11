# Skill: translate

## 简介

中英互译（默认其他语言→中文），复用 DeepSeek provider，不需要额外 API key。

## 触发词

- `翻译`
- `translate`
- `trans`

## 输入 → 输出

| 用户发 | bot 回 |
|---|---|
| `翻译 hello world` | `你好世界` |
| `翻译 你好` | `Hello` |
| `translate こんにちは` | `你好` |
| `翻译`（没跟内容）| `翻译啥？比如『翻译 hello world』。` |

## 工作流

1. handler 去掉触发词，剩下的喂 DeepSeek
2. system prompt 让 DeepSeek 自动判断源语言（中/英自动互译，其他→中文）
3. 严格输出译文本身（无前缀、无解释、无对照）

## 安全边界

- 无外部 API 调用（复用项目 DEEPSEEK_API_KEY）
- 无文件 IO
- 上限 600 token，长文本会被截断
- 翻译失败兜底友好提示，不抛异常

## 给 @claude 的提示

如果要扩展：
- 支持指定目标语言（"翻译成日语 hello"）→ 改 `_SYS` 提示词加规则 + 解析触发词后的语言名
- 支持多段长文 → 拆段 + 并行调 provider.complete
- 不要改成双语对照默认；用户要直白结果
