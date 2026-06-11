# Skill: echo

## 简介

复读机——把触发词后面那段文字原样返回。

主要给"看 P12.3 工具契约"的人示范用，不解决实际业务问题。

## 触发词

- `echo`
- `回声`
- `复读`

任一 substring 命中即触发。

## 输入 → 输出

| 用户发 | bot 回 |
|---|---|
| `echo 你好` | `📣 你好` |
| `回声 hello world` | `📣 hello world` |
| `复读我说的话` | `📣 我说的话` |
| `echo`（没跟内容）| `请在触发词后面跟一段文字，比如『echo 你好』` |

## 常见误判

- "复读机" / "echo 服务器" 这种**有触发词但用户其实是想聊天**的——当前实现仍会触发返回。未来想做的话，可以在 handler 里加 LLM 一句 YES/NO 兜底。

## 安全边界

- 无外部 API 调用
- 无文件 IO
- 无网络
- 无敏感数据接触
- 输出最多就是 substring，没注入风险

## 给 @claude 的提示

如果你（Claude）要在 `wechat/tools/` 加新工具，**仿照这个目录结构**：
1. 建 `wechat/tools/<新工具名>/`
2. `handler.py` 里实现 `TOOL_NAME` / `TRIGGER_KEYWORDS` / `handle(text, ctx)`
3. `SKILL.md` 写清楚：简介 / 触发词 / 输入输出 / 常见误判 / 安全边界

dispatcher 启动时自动发现，无需注册代码。
