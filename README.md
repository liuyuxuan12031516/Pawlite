# Pawlite

一个自己写着玩的本地 Agent，后端主要接 Qwen / DashScope。

我想要的东西很简单：在命令行里丢一句任务，它能自己拆步骤，然后用本地工具去读文件、搜文件、写文件、跑命令。写文件和 shell 默认都会问一下，避免模型一上来就乱改东西。

灵感有一部分来自 [OpenClaw](https://github.com/openclaw/openclaw)，但这个仓库是我自己拆出来写的，跟 QwenPaw 也没关系。

## 现在大概能干什么

- 读写 workspace 里的文本文件
- 搜文件名、搜图片
- 读 Excel，支持按文件、sheet、行数分批
- 调 Qwen 多模态看图
- 跑一些安全检查过的 shell 命令
- 记一点本地 memory
- 复杂任务时用 Planner / Executor 分开跑，尽量别把一大坨原始内容塞进上下文

## 代码结构

```text
pawlite/
├── cli.py          # 命令行入口，负责参数和输出
├── config.py       # 从 .env / 环境变量 / CLI 参数里组配置
├── agent.py        # Planner + Executor 主循环
├── qwen_client.py  # Qwen / DashScope 请求封装
├── skills.py       # 真正能执行的本地工具
└── memory.py       # .pawlite_memory.json
```

还有一个 `skills/` 目录，放的是给 Planner 参考的外部 skill 文档。这个目录里的东西不会直接变成工具，只会先把名称和描述压缩给 Planner 看；如果它觉得某个 skill 有用，会发一个 `read_skill`，运行时再把对应 `SKILL.md` 读出来作为 report 还给 Planner。

也就是说：

- `pawlite/skills.py` 里的工具是真正能执行的工具
- `skills/*/SKILL.md` 更像是 Planner 的说明书，按需看，不每次全塞进提示词

## Planner / Executor

`agent.py` 里分了两层：

Planner 只负责决定下一步，比如要不要先预览目录、要不要读某个 skill、要不要把一个小任务交给 Executor。

Executor 才会拿到具体子任务，然后调用 `list_files`、`read_file`、`read_excel`、`run_shell` 这些工具。做完以后 Executor 会给 Planner 一份简短 report，Planner 再决定下一步。

大概是这个循环：

```text
用户任务
  -> Planner 决定下一步
  -> Executor 执行一个小任务
  -> 返回 compact report
  -> Planner 继续判断
  -> 完成
```

这里故意不让 Planner 自己直接跑工具，这样状态会清楚一点，也方便限制每一步的范围。

## 内置工具

主要工具都在 `SkillRegistry` 里：

- `list_files`：列 workspace 里的文件
- `read_file`：读文本文件
- `search_files`：按文件名搜
- `find_images`：按文件名搜图片
- `read_excel` / `read_excel_directory`：读 Excel，支持 offset 分页
- `describe_image`：把图片交给多模态模型看
- `write_file` / `append_file`：写文件，默认要确认
- `run_shell`：跑 shell，默认要确认，也会拦一些危险命令
- `remember` / `search_memory`：本地记忆
- `now`：当前时间

复杂任务会尽量引导它先 preview，再分批处理，中间结果可以写到 `.pawlite_work/`，不要把 Excel 原始行、命令长输出之类的东西直接整坨写进上下文。

## 配置

根目录放一个 `.env`：

```env
DASHSCOPE_API_KEY=你的key
DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com/api/v1
DASHSCOPE_MODEL=qwen3.6-plus
```

`.env` 已经在 `.gitignore` 里，不要把真实 key 提交上去。

配置优先级大概是：

```text
CLI 参数 > .env > 系统环境变量 > 默认值
```

## 用法

跑一个任务：

```bash
python -m pawlite "列出当前目录，然后一句话总结"
```

进入交互模式：

```bash
python -m pawlite
```

写文件或者跑 shell 时，如果不想每次确认：

```bash
python -m pawlite "创建 notes/idea.md，写三条迭代计划" --yes
```

复杂一点的任务可以多给几步：

```bash
python -m pawlite "读取 README.md 和 examples/tasks.md，总结项目结构" --max-steps 12
```

看图片：

```bash
python -m pawlite "看看这张图里有什么" --image path/to/image.png
```

离线 smoke test，不连模型：

```bash
python -m pawlite "创建 hello_pawlite.txt 写入: hello pawlite" --offline --yes
```

常用参数：

- `--workspace`：指定工作目录
- `--api-key` / `--base-url` / `--model`：临时覆盖配置
- `--language`：指定输出语言，默认中文
- `--yes`：自动确认写文件、append、shell
- `--offline`：不用模型，简单测流程
- `--max-steps`：最多跑多少轮
- `--no-stream`：关流式输出
- `--json`：打印原始事件 JSON
- `--verbose`：显示更完整的工具参数
- `--image`：附加图片路径，可以传多次

更多随手写的例子在 `examples/tasks.md`。

## 本地测试

现在有一个很简单的 smoke test：

```bash
python test_pawlite.py
```

主要检查配置、memory、技能注册、Agent 初始化，以及根目录 `skills/` 里的 Planner skill 能不能被扫到。
