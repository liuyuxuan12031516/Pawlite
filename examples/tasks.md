# Pawlite 示例任务

## 基础

```bash
python -m pawlite "列出当前目录，然后用一句话总结"
```

```bash
python -m pawlite "创建 notes/idea.md，写入一个三点的 Pawlite 迭代计划" --yes 
```

```bash
python -m pawlite "读取 README.md，然后读取整个项目的所有代码，总结这个项目的架构，并把总结和分析写到一个txt文件里面。" --yes
```

```bash
python -m pawlite "读取 README.md，然后读取整个项目的所有代码，了解这个项目的架构，并根据我的项目写一个测试代码，并且成功运行以确认项目代码没有问题" --yes --max-steps 12
```

```bash
python -m pawlite "请使用 web_search 搜索今天最新的 Qwen 模型相关消息，并用三句话总结重点" --max-steps 4 --yes
```

## 离线 smoke test

```bash
python -m pawlite "创建 hello_pawlite.txt 写入: hello pawlite" --offline --yes
```

## 多步验收

```bash
python -m pawlite "请完成一个多步验收任务：1.列出当前项目根目录文件；2. 读取 README.md 和 examples/tasks.md；3. 运行 python -m pawlite --version；4. 创建 pawlite_complex_report.md，写入你对这个项目的架构总结、可用命令示例、以及刚才版本命令的输出；5. 把一句话结论记到 memory 里。"  --yes
```

## Excel 分析

```bash
python -m pawlite "读取 C:\Users\13950\Desktop\个人信息\工作周报 目录下的 Excel，汇总内容并写一份总结到 weekly_report_summary.md"  --yes --max-steps 6
```

```bash
python -m pawlite "请完成一个复杂多步分析任务：读取 C:\Users\13950\Desktop\个人信息\工作周报 目录下的 Excel。要求先小批量读取，不要一次性读取过大文本；先分析每一周的工作内容，包括时间、核心工作、所属项目、关键进展、未完成问题、下周计划；再汇总所有项目进展，整理时间线分析、推进情况分析、风险与遗留问题、后续建议；最终写入 weekly_report_summary_complex.md；如果工具无法真正跳过已读文件或分页读取，请在文件末尾说明限制和实际策略。"  --yes --max-steps 12
```

```bash
python -m pawlite "请在 C:\Users\13950\Desktop 下查找图片文件，先最多找 3 张；然后用 describe_image 逐张查看画面内容；最后按表述列出：文件路径、画面主要内容、可见文字、可能用途。不要打开超过 3 张图片。" --base-url "https://dashscope.aliyuncs.com/compatible-mode/v1" --yes --max-steps 8
```
