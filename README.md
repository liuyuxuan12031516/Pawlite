# Pawlite

自己写的一个本地 Agent，后端用的 Qwen / DashScope。

基本用法是在命令行里丢任务，它会自己拆步骤、调工具、读写文件。写文件和跑 shell 默认要确认。灵感来自 [OpenClaw](https://github.com/openclaw/openclaw)，独立项目，跟 QwenPaw 没关系。

## 整体结构

```text
pawlite/
├── cli.py          # 命令行入口
├── config.py       # 读 .env、组装 Config
├── agent.py        # Planner + Executor 主循环
├── qwen_client.py  # 调 DashScope / Qwen
├── skills.py       # 本地工具集
└── memory.py       # .pawlite_memory.json 持久记忆
```

Planner 和 Executor 都走同一套 JSON 协议，只是 Planner 用 `delegate`，Executor 用具体 `tool` 名。

**Planner 返回示例：**

```json
{
  "thought": "先看看目录里有什么",
  "final": null,
  "actions": [
    {
      "type": "delegate",
      "task": {
        "title": "列出项目文件",
        "objective": "列出 workspace 根目录",
        "instructions": "用 list_files，path 设为 .",
        "success_criteria": ["拿到文件列表"]
      },
      "reason": "需要先了解项目结构"
    }
  ]
}
```

**Executor 返回示例：**

```json
{
  "thought": "执行 list_files",
  "final": null,
  "actions": [
    {"tool": "list_files", "args": {"path": "."}, "reason": "列目录"}
  ]
}
```

子任务做完后 Executor 会给 Planner 一份 compact report（`status` / `summary` / `artifacts` / `limitations`），Planner 再决定下一步。

## 内置 Skills

| 工具 | 干什么 | 要不要确认 |
|------|--------|------------|
| `list_files` | 列 workspace 内文件 | 否 |
| `read_file` | 读文本文件 | 否 |
| `search_files` / `find_images` | 按文件名搜文件/图片 | 否 |
| `read_excel` | 读 xlsx，支持分页 offset | 否 |
| `describe_image` | 多模态看图 | 否 |
| `remember` / `search_memory` | 本地记忆读写 | 否 |
| `now` | 当前时间 | 否 |
| `write_file` / `append_file` | 写 workspace 内文件 | 是（`--yes` 跳过） |
| `run_shell` | 跑 shell，带危险命令拦截 | 是 |

注册在 `SkillRegistry` 里，大概长这样：

```python
self._skills = {
    "list_files": self.list_files,
    "read_file": self.read_file,
    "write_file": self.write_file,
    "describe_image": self.describe_image,
    "read_excel": self.read_excel,
    # ...
}
```

复杂任务的长文本/Excel 会建议写到 `.pawlite_work/` 做中间笔记，避免把原始工具输出整坨塞进上下文。

## 怎么用

根目录 `.env` 配 key：

```env
DASHSCOPE_API_KEY=你的key
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/api/v1
DASHSCOPE_MODEL=qwen3.6-plus
```

跑任务：

```bash
python -m pawlite "列出当前目录，然后一句话总结"
```

交互模式：

```bash
python -m pawlite
```

`qwen3.6-plus` 建议加 compatible-mode，稳一点：

```bash
python -m pawlite "你好" --base-url "https://dashscope.aliyuncs.com/compatible-mode/v1"
```

常用参数：`--yes` 自动确认写文件，`--offline` 不连模型测流程，`--max-steps 12` 复杂任务多跑几步，`--no-stream` 关掉流式输出。

更多例子看 `examples/tasks.md`。
