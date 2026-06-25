---
name: project-architecture-testing
description: Guides project architecture understanding and core test generation. Use when the user asks to read README/project code, understand the architecture, write test code, run tests, verify the project, or repeat a previous architecture-and-testing workflow.
---

# Project Architecture Testing

## When To Use

Use this skill for tasks like:

- 读取 `README.md` 和项目代码，理解项目架构。
- 根据项目架构编写测试代码。
- 运行测试确认核心模块没有明显问题。
- 用户重复要求“读取整个项目、了解架构、写测试并成功运行”。

## Fast Workflow

1. Check existing context before rereading everything:
   - Search memory for recent `architecture_summary` or similar task/final entries.
   - Check whether `.pawlite_work/project_preview.txt` or `.pawlite_work/project_preview.json` already exists.
   - Reuse recent summaries as hints, but verify against current source before changing tests.
2. Preview scope once:
   - Read `README.md`.
   - List the root directory and main source directory.
   - Identify entrypoints, config, agent/orchestration, tool/skill registry, memory, and client modules.
3. Read source in architecture order:
   - Entrypoint/CLI first.
   - Config and client setup.
   - Agent orchestration.
   - Skill/tool registry.
   - Memory/storage.
   - Tests/examples last.
4. If `read_file` returns `truncated=true`, continue with `offset=next_offset` only for files needed by the task.
5. Write compact findings to `.pawlite_work/project_preview.txt` only when useful. Do not save raw source dumps.
6. Generate tests from actual APIs in source, not guessed method names.
7. Run the test command. If it fails, read the exact source for the failing API, update the test, and rerun.
8. Finish only after the test command exits successfully, or clearly report the blocker.

## Pawlite-Specific Defaults

For this repository, a good first-pass core test should cover:

- `Config.from_env(workspace)` creates a usable config object.
- `Memory(path=...)` can add and persist a test record.
- `SkillContext` and `SkillRegistry` initialize and expose core skills such as `list_files` and `read_file`.
- `PawliteAgent(config=...)` initializes `config`, `skills`, and `memory`.

Prefer testing stable initialization and local behavior. Do not require live Qwen/DashScope API calls for a basic project health test.

## Efficient Subtasks

Use two executor subtasks instead of many tiny ones:

1. `预览项目结构与读取核心代码`
   - Read `README.md`.
   - List root and `pawlite`.
   - Read core files needed for architecture and test design.
   - Write or refresh `.pawlite_work/project_preview.txt`.
2. `编写并运行核心测试`
   - Read the preview and any exact APIs needed.
   - Write `test_pawlite.py`.
   - Run `python test_pawlite.py`.
   - Save a short `.pawlite_work/test_results.txt` with command, exit status, and tested areas.

## Completion Criteria

Before finalizing, verify each user requirement explicitly:

- README was read.
- Relevant project code was read; if not truly all files, say “核心代码” or list limitations.
- Architecture understanding was summarized or used to design tests.
- Test code was written or updated.
- Test command ran successfully.

Avoid claiming “读取整个项目代码” unless coverage metadata supports that claim.
