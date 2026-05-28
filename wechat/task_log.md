# WeChat 任务流水

> 由 dispatcher 调起的 Claude Code 子进程在每次任务结束后追加一条记录。
> 用于给下一次 Claude Code 任务做"短期上下文"。
> dispatcher 本身不读不写这个文件——是 Claude Code 自己读、自己加。

格式约定：

```
## YYYY-MM-DD HH:MM · 用户：<user_id>
**请求**：<原始请求>
**方案概要**：<一句话>
**改动**：<文件列表>
**Commit**: 未提交 / <hash>
```

---
