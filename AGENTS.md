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

- Prefer existing modules, controllers, repositories, and views instead of adding parallel implementations.
- Keep dependencies minimal. If a new dependency is necessary, explain why the standard library or current packages are insufficient.
- Avoid adding telemetry, remote logging, or cloud tracking.
- Keep UI behavior and naming consistent with the surrounding code.
- Avoid broad refactors unless the user asked for them.
- If you need to touch database logic, preserve existing data and migration behavior.

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
