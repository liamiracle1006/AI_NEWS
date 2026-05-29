# `wechat/tools/` 命令式工具插件

每个 `.py` 文件 = 一个工具。dispatcher 在 `parse_intent` 失败后、`chat_fallback` 之前
调 `find_tool(text)` 看有没有工具能接住。

## 契约（每个工具必须有这 3 个）

```python
# wechat/tools/your_tool.py

TOOL_NAME = "your_tool"                  # 唯一标识
TRIGGER_KEYWORDS = ("kw1", "kw2")        # substring 匹配；命中任一即触发
                                         # 大小写不敏感

def handle(text: str, ctx) -> str:
    """text = 用户原消息全文；ctx = Dispatcher（一般用不到）。
    返回纯文本，dispatcher 自动发到微信。
    """
    return "your reply"
```

## 当前工具

| 工具 | 关键词 | 用途 |
|---|---|---|
| `echo` | `echo` / `回声` / `复读` | 复读机示范 |

## 加新工具的两种方式

### A. 你自己写（VS Code 这边）

1. 在 `wechat/tools/` 新建 `your_tool.py`，遵循契约
2. 微信发『重启』
3. 测：发命中关键词的消息

### B. 微信走 @claude 加（推荐——快）

```
新增加功能：在 wechat/tools/ 仿照 echo.py 加一个【天气查询】工具，
触发词 "天气" / "weather"，参数是城市名，
用 open-meteo 的免 key API（先 geocode 再查天气）。
起名 weather
```

phase-1 给方案 → 回『执行』 → phase-2 改完 → 发『重启』 → 测试。

## 异常隔离

工具 `handle()` 抛异常 → dispatcher 兜底回 `❌ 工具 X 出错: TypeError: ...`，bot **不崩**。

## 工具 vs 项目（Phase 11）

| 是 | 不是 |
|---|---|
| **tools/**：无状态命令（查天气 / 查股价 / 翻译） | **projects/**（未来）：有状态业务（AI_NEWS / AI_Accounting）|
| 每次调用独立 | 共享数据库 / 长生命周期 |
| 一个文件 < 100 行 | 自己有 backend |

AI_Accounting 这种**整个项目**接进来时会用 `wechat/projects/` 而不是这里——见 plan Phase 11。
