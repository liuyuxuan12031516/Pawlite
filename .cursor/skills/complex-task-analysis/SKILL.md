---
name: complex-task-analysis
description: Guides agents through complex multi-step analysis, long files, directories, spreadsheets, and report synthesis. Use when a task requires planning, previewing large inputs, chunked execution, intermediate artifacts, or final consolidation.
---

# Complex Task Analysis

## Core Pattern

Use a planner-executor workflow for complex tasks:

1. Frame the objective, inputs, outputs, constraints, and success criteria.
2. Preview source size and structure with small reads before loading content.
3. Design chunk boundaries and intermediate schemas from the preview.
4. Execute bounded chunks one at a time.
5. Save compact intermediate notes when the task is long or evidence-heavy.
6. Synthesize from intermediate notes, not from raw source text held in context.
7. Verify coverage and disclose limitations.

## Long File Strategy

For超长文件、目录、表格、日志、报告、批量文档:

- First inspect metadata: file count, file names, file sizes when available, sheet/page counts, sample rows, headings, and truncation flags.
- Do not read an entire large source in one step. Start with a small preview.
- If preview output is truncated or too broad, reduce batch size or narrow by file, page, sheet, row range, topic, or date.
- Prefer complete coarse coverage before deep analysis of a few early chunks.
- Keep every intermediate note much shorter than its source chunk.

## Intermediate Work

Use a workspace directory such as `.pawlite_work/` when useful:

- `plan.md`: current objective, plan, chunk strategy, and open questions.
- `chunk_notes.jsonl`: one compact record per processed chunk.
- `coverage.json`: processed files/ranges, skipped inputs, and tool limitations.

Intermediate notes should include provenance such as source path, sheet/page/row range, timestamp, and confidence or unresolved questions.

## Excel Handling

Excel tools should stay generic. Given a path, parse workbook content and return structure plus bounded text.

- Preview with small limits first, such as one or two files, a few sheets, a few rows, and a small character cap.
- For directories, page by sorted file offset.
- For workbooks, page by sheet offset and row offset when available.
- Treat unsupported formats and truncation as coverage facts to report later.

## Final Synthesis

Before writing the final result:

- Reconcile duplicated or conflicting facts across chunks.
- Separate evidence-backed findings from assumptions.
- Do not fill missing evidence with plausible details. Mark unclear items as uncertain.
- Check the output against every explicit user requirement.
- Include a short limitations section if any source was skipped, truncated, unsupported, or only approximately paged.
