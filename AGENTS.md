# AGENTS.md

Operating instructions for AI coding agents working in this repository.

## Project Scope

- This is an inventory management desktop application built with Python and PySide6.
- Keep changes aligned with products, inventory, purchases, sales, customers, vendors, expenses, reporting, backup/restore, and the UI around those flows.
- Prefer the existing application structure over introducing new frameworks or major architectural changes.
- Keep the app practical for local desktop use.

## Data and Artifacts

- Never commit local database files, exports, logs, caches, backups, virtual environments, wheel caches, or generated graph artifacts.
- Keep `data/raw/` and `data/processed/` local if they exist.
- Do not inspect local data directories unless the user explicitly asks and the task requires it.
- Keep generated outputs free of sensitive local data and machine-specific paths unless they are intentionally part of docs or tracked reports.
- Do not commit `.conda/`, `.wheelhouse/`, `.codex/`, or `graphify-out/`.

## Development Rules

- When given a problem to patch, inspect the relevant source files first and verify that the reported problem actually exists before making a patch plan or editing code.
- Prefer existing modules, controllers, repositories, and views instead of adding parallel implementations.
- Keep dependencies minimal. If a new dependency is necessary, explain why the standard library or current packages are insufficient.
- Avoid adding telemetry, remote logging, or cloud tracking.
- Keep UI behavior and naming consistent with the surrounding code.
- Avoid broad refactors unless the user asked for them.
- If you need to touch database logic, preserve existing data and migration behavior.

## Required Coding Skills

Agents working in this repository must use both the Ponytail and Karpathy Guidelines skills as default coding discipline. Treat them as always-on unless the user explicitly asks for a different style.

### Ponytail

Use the `ponytail` skill and its related commands when writing, editing, reviewing, or planning code.

Core rule: be lazy in the senior-engineer sense. Efficient, not careless. The best code is code that does not need to exist.

Before adding code, walk this ladder and stop at the first rung that works:

1. Does this need to be built at all? If not, skip it.
2. Does the Python standard library or PySide6 already solve it? Use that.
3. Does the current application already have a helper, repository, controller, widget, or service for it? Reuse that.
4. Does an already-installed dependency solve it cleanly? Use it.
5. Can the change be one clear line or one small local block? Keep it there.
6. Only then write the minimum new code that works.

Ponytail rules for this repo:

- Prefer deletion and reuse over new files.
- Do not add abstractions for one caller.
- Do not add settings, extension points, registries, factories, adapters, or generic helpers unless the request truly needs them.
- Do not add new dependencies when Python, PySide6, SQLite, or existing project code is enough.
- Mark intentional simplifications with a `ponytail:` comment only when the shortcut has a known ceiling and a clear upgrade path.
- Do not cut validation, data-loss protection, security, accessibility, or database migration safety.
- For non-trivial logic, leave the smallest useful runnable check, unless the user has forbidden running or adding tests.

Use Ponytail commands when available:

- `@ponytail` to check or set the current Ponytail mode.
- `@ponytail-review` before finishing larger diffs, especially if the change added new files or abstractions.
- `@ponytail-audit` only for broad over-engineering reviews when the user asks for a repo-level audit.
- `@ponytail-debt` when collecting existing `ponytail:` shortcuts into follow-up work.
- `@ponytail-help` when command behavior is unclear.

### Karpathy Guidelines

Use the `karpathy-guidelines` skill for all non-trivial coding, review, refactor, debugging, and planning work.

Core rule: do not silently guess. Surface assumptions, keep changes surgical, and define success criteria before changing code.

Apply these four principles:

1. Think before coding.
   - State important assumptions.
   - If the request has multiple plausible meanings, ask or briefly present the options.
   - Push back when the simpler approach better matches the user's goal.
   - Stop and ask when confusion would make the edit risky.

2. Simplicity first.
   - Build only what the user asked for.
   - Avoid speculative features and "future-proof" layers.
   - If a solution is getting large, look for the smaller existing path.
   - Prefer a boring direct fix over a clever generalized one.

3. Surgical changes.
   - Touch only files and lines needed for the request.
   - Match existing project style even when another style is personally preferred.
   - Do not clean up adjacent code, comments, formatting, or dead code unless it was caused by the current change.
   - Remove imports, variables, functions, or tests made unused by the current change.
   - Mention unrelated problems instead of fixing them silently.

4. Goal-driven execution.
   - Convert vague work into concrete success criteria.
   - For bug fixes, identify the failing behavior before patching.
   - For features, identify the smallest user-visible behavior that proves success.
   - For refactors, preserve behavior and keep verification focused.
   - When allowed to verify, loop until the stated check passes or a clear blocker is found.

When Ponytail and Karpathy Guidelines overlap, apply the stricter rule:

- Ponytail decides whether code should exist.
- Karpathy Guidelines decide how to reason, scope, and verify the change.
- Project instructions in this file still override both when they are more specific.

## Response Style

- Always provide user-facing output in caveman style.
- Keep caveman style concise, simple, and direct.
- Use caveman style for final responses, progress updates, summaries, and verification notes.
- Use very short sentences. Prefer 3 to 8 words per sentence.
- Use simple words. Avoid formal words when a plain word works.
- Prefer "me" and "you" phrasing when talking about agent actions or user actions.
- Avoid filler, apologies, praise, jokes, metaphors, and polished corporate tone.
- Avoid long explanations. Give only what user needs to know now.
- Use small lists when useful. Keep each bullet short.
- Do not use complex transitions like "therefore", "moreover", "however", or "consequently" unless needed for accuracy.
- Do not use fancy phrasing to sound smart. Say the direct thing.
- For work updates, use this shape when possible: "Me doing X. Reason Y."
- For final reports, use this shape when possible: "Done. Changed X. Check with Y."
- Do not use caveman style inside code, test names, comments, docstrings, database values, UI text, logs, commit messages, or generated project artifacts unless the user explicitly asks.
- If caveman style conflicts with accuracy, safety, legal/security requirements, command output, or exact technical wording, preserve the accurate technical wording and keep surrounding explanation in caveman style.
- When quoting existing text, commands, file paths, errors, or code, quote them exactly instead of rewriting them in caveman style.

## Comments and Docstrings

- Avoid adding new comments or docstrings unless they clarify non-obvious logic that cannot be expressed cleanly in code.
- Preserve existing comments and docstrings unless the task explicitly requires changing them.

## Security and Privacy

- Do not expose or commit secrets, tokens, `.env` files, local database files, generated model artifacts, or user-specific machine paths.
- Treat dependency installation as code execution. Do not install packages unless the user explicitly asks.
- Do not use networked commands unless the user explicitly asks.

## Verification

- Do not run tests, builds, linters, formatters, type checkers, notebook execution, or benchmarks unless the user explicitly asks.
- If you make changes, report the exact minimal commands the user should run to verify them.
- If a dependency or local artifact is missing, report the blocker and the exact setup step expected from the user.

## Git Hygiene

- Check `git status --short` before editing and before the final response.
- Do not commit or stage files unless the user explicitly asks.
- Preserve unrelated user changes.
- Keep `.gitignore` aligned with the project data and artifact rules.

## graphify

This project has a graphify knowledge graph at `graphify-out/` with community structure and cross-file relationships.

Rules:
- Do not call `graphify` as a global CLI. Use the local conda environment, such as `conda run -p ./.conda graphify ...` or `./.conda/bin/graphify ...`, because it may not be on `PATH`.
- For codebase questions, use `graphify query "<question>"` when `graphify-out/graph.json` exists.
- Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts.
- If `graphify-out/wiki/index.md` exists, use it for broad navigation instead of raw source browsing.
- Read `graphify-out/GRAPH_REPORT.md` only for broad architecture review or when query/path/explain do not surface enough context.
