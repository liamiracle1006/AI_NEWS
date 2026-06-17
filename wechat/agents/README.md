# `wechat/agents/` — Subagent 配置（P13.2 + P13.5）

每个 `.json` 定义一个 agent，dispatcher 在 `@claude (name) ...` 时用对应配置跑。

## 内置 agent

| 名字 | 模型 | 用途 |
|---|---|---|
| `code` | 默认（订阅 Claude）| **默认**——@claude 无 `(name)` 时用，全功能 |
| `research` | `haiku-4-5` | 只读：commit 查询 / 跨项目对比 / 代码摸底 |
| `summary` | `haiku-4-5` | 纯文本总结，几乎零工具 |
| `deepseek_coder` | `deepseek-chat` | 用 DeepSeek 写代码（**需要 LiteLLM 代理**）|

发 `列出 agents` / `agents` 可微信里看注册情况。

## 配置字段 schema

```json
{
  "name": "唯一标识（不传则用文件名 stem）",
  "description": "给用户看的简短说明",
  "model": "传给 claude --model（haiku-4-5 / sonnet-4-6 / opus-4-7 / 留空=默认）",
  "system_prompt": "追加到 PHASE_1/2_PROMPT 之前的额外指令（留空=不追加）",
  "allowed_tools": ["Read", "Bash"],      // 白名单，传给 --allowedTools；留空 = 不限制
  "disallowed_tools": ["Write", "Edit"], // 黑名单，合并 P12.6 sandbox 已有的；留空 = 不限制
  "env": {                                // P13.5 · subprocess env 覆盖
    "ANTHROPIC_BASE_URL": "...",          // 例：换代理地址
    "ANTHROPIC_API_KEY": "..."            // 例：代理需要的假 key
  }
}
```

注释字段（`_` 开头如 `_doc`、`_setup`、`_status`）会被 loader 忽略，仅供人读。

## 启用 deepseek_coder（用 DeepSeek-V3 写代码）

**为啥要这么干**：DeepSeek-V3 单 token 成本约是 Claude Sonnet 的 1/10。如果你 Claude
Pro/Max 配额经常吃满，切到 DeepSeek 跑某些非关键路径很省。

### Step 1: 起 LiteLLM 代理（一次性）

```bash
# 装
pip install 'litellm[proxy]'

# .env 加（DeepSeek 平台拿 key）
DEEPSEEK_API_KEY=sk-xxxxxxxx

# 起代理（前台跑，建议 tmux/screen）
litellm --model deepseek/deepseek-chat --port 11434
```

或者用 [claude-code-router](https://github.com/musistudio/claude-code-router) 这种现成方案，
能同时支持多个后端模型。

### Step 2: 验证代理工作

```bash
curl http://localhost:11434/v1/chat/completions \
  -H "Authorization: Bearer sk-litellm-fake" \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-chat","messages":[{"role":"user","content":"hi"}]}'
```

返回 200 + JSON 才算 OK。

### Step 3: 微信里用

```
@claude (deepseek_coder) 加个查美股的工具
```

bot 会用 DeepSeek 跑可行性 + 写代码。

## 自定义新 agent

两种方式：

**A. 提交进项目**（团队共享）：
```
wechat/agents/<myname>.json
```
重启 bot 即注册。

**B. 私有定制**（不进 git）：
```
~/.ai_news/workspace/agents/<myname>.json
```
13.3 workspace 优先级高于内置；同名 agent workspace 胜出。

## 注意

- agent 加载是启动时一次性扫；改 .json 后要重启或将来加"重载 agent"命令
- system_prompt 不能太长——会跟 PHASE_1/2_PROMPT 一起被注入，太长 LLM 跟随度下降
- env 字段会**覆盖** subprocess 当前 env，包括 `_run_claude_subprocess` 默认 `pop`
  的 `ANTHROPIC_API_KEY`——如果你 agent 需要一个假 key 走代理，就在 env 里写

## 当前没接但可以一行加的

- `gpt4`（OpenAI 后端，用同样 LiteLLM 路由）
- `gemini`（Google 后端）
- `llama-local`（本地 Ollama）

模式都一样：proxy + 改 `model` + 改 `env`。
