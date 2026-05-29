# 深度分析速度优化方案（plan 番外节选）

当前 10 篇 article 跑完 **fact-extract + cross-ref + entity-tracking** 约 2–5 分钟。
瓶颈在 LLM 串行调用，不在 Python 代码。**改完理论能把 3 分钟降到 1–1.5 分钟**。

| ID | 方案 | 收益 | 代价 | 改的位置 |
|---|---|---|---|---|
| A | fact-extract 并发 5 → 10 | -25%~40% | DeepSeek 可能 rate limit，需重试 | `news/pipeline.py:extract_facts_batch` |
| B | cross_reference & track_entities 并行 | -10~20s | 几行 ThreadPoolExecutor | `news/pipeline.py:analyze_topic` |
| C | "快速模式"：跳过正文抓取，仅用 summary+title | -5~30s | 可能丢 key_quotes / 部分 context | `news/pipeline.py:analyze_topic` + 增加 fast_mode 字段 |

推荐先做 A+B+C（半小时左右就能完成），效果立竿见影。
做时记得：测一组 baseline 时间，改完再测一次，写在 commit 里。

## 本次任务要求

1. 实现上表 A+B+C 三项
2. A 项把并发提升到 10 时，给 DeepSeek 调用加上指数退避重试（plan 里明确标出的代价项）
3. C 项的 fast_mode 通过 `/api/analyze` 请求的 query 参数或 body 字段开启，默认关闭
4. 实现前后各跑一次 baseline（同一关键词、同一时段），把耗时记录到 commit message
