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

## Accounting Module Guardrails

- All future accounting-related calculations must go through `modules/accounting/service.py` or approved accounting service APIs.
- Do not add new payable, receivable, advance, credit, debit, vendor balance, customer balance, inventory valuation, bank balance, or profit/margin calculations directly inside vendor, purchase, sales, customer, inventory, expense, or UI modules.
- Existing scattered calculations may remain temporarily during the migration.
- When touching existing accounting behavior, first add characterization tests that capture current behavior.
- Do not silently change accounting behavior while scaffolding.
- Do not introduce external ERP/accounting dependencies without explicit approval.
- Any future ledger implementation must preserve double-entry invariants and source-document traceability.

## Required Coding Skills

Agents working in this repository must use the Karpathy Guidelines skill as default coding discipline. Treat it as always-on unless the user explicitly asks for a different style.

Enforcement rules for this repository:

- Agents must strictly adhere to the Karpathy Guidelines for every non-trivial task in this repo.
- Agents must not silently skip these disciplines because a task looks familiar, repetitive, or easy to improvise.
- If a request is ambiguous, agents must ask instead of guessing, these questions should be in plain english with easy to understand example scenario.
- If a solution grows beyond the smallest reasonable change, agents must simplify before continuing.
- If a task requires multiple steps, agents must state a brief goal-driven plan before editing.
- If a code change is made, every changed line must trace directly to the user request or to test/code cleanup caused by that change.
- Agents must preserve current behavior first when migrating or consolidating legacy logic unless the user explicitly asks for a behavior change.
- Agents must prefer characterization tests before refactoring behavior-heavy code.
- Agents must not add speculative abstractions, configurability, or future-proofing layers that were not requested.
- Agents must not silently fix unrelated code while touching a nearby area; unrelated issues should be mentioned, not folded into the same change.

### Karpathy Guidelines

Use the `karpathy-guidelines` skill for all non-trivial coding, review, refactor, debugging, and planning work.

Core rule: do not silently guess. Surface assumptions, keep changes surgical, and define success criteria before changing code.

These rules are mandatory in this repository. If there is any tension between speed and these guidelines, prefer the guideline-compliant path unless the user explicitly asks for a fast exploratory pass.

Behavioral guidelines to reduce common LLM coding mistakes, derived from [Andrej Karpathy's observations](https://x.com/karpathy/status/2015883857489522876) on LLM coding pitfalls.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

Apply these four principles:

1. Think before coding.
   - State your assumptions explicitly.
   - If uncertain, ask.
   - If multiple interpretations exist, present them and do not pick silently.
   - If a simpler approach exists, say so.
   - Push back when warranted.
   - If something is unclear, stop.
   - Name what is confusing.
   - Ask.

2. Simplicity first.
   - Build the minimum code that solves the problem.
   - Add no features beyond what was asked.
   - Add no abstractions for single-use code.
   - Add no "flexibility" or "configurability" that was not requested.
   - Add no error handling for impossible scenarios.
   - If a solution is getting large, stop and look for the smaller existing path.
   - Prefer a boring direct fix over a clever generalized one.
   - Ask: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

3. Surgical changes.
   - Touch only files and lines needed for the request.
   - Match existing project style even when another style is personally preferred.
   - Do not "improve" adjacent code, comments, or formatting unless it was caused by the current change.
   - Do not refactor things that are not broken unless the user asked.
   - Remove imports, variables, functions, or tests made unused by the current change.
   - Do not remove pre-existing dead code unless asked.
   - Mention unrelated problems instead of fixing them silently.
   - The test: every changed line should trace directly to the user's request.

4. Goal-driven execution.
   - Convert vague work into concrete success criteria.
   - For bug fixes, identify the failing behavior before patching.
   - For features, identify the smallest user-visible behavior that proves success.
   - For refactors, preserve behavior and keep verification focused.
   - For multi-step tasks, state a brief plan in this shape when useful:
     1. [Step] -> verify: [check]
     2. [Step] -> verify: [check]
     3. [Step] -> verify: [check]
   - Strong success criteria should let the agent loop independently.
   - Weak success criteria like "make it work" require clarification and should be tightened before editing.
   - When allowed to verify, loop until the stated check passes or a clear blocker is found.

Project instructions in this file still override the Karpathy Guidelines when they are more specific.

Required behavior from agents using these guidelines:

- Before implementation, briefly state assumptions when they materially affect the change.
- Before editing behavior-heavy code, identify the exact behavior to preserve.
- Before editing multi-step tasks, provide a short plan tied to verification.
- After editing, report verification steps or blockers explicitly.
- Do not hide uncertainty behind implementation.

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

- Always write or update test files when making code changes, using the smallest useful coverage for the change.
- Do not run tests under any condition unless the user explicitly asks you to run tests in the current turn.
- Do not run test commands indirectly through scripts, make targets, IDE helpers, pre-commit hooks, or app startup smoke checks unless the user explicitly asks for that exact verification.
- Do not run builds, linters, formatters, type checkers, notebook execution, benchmarks, or app startup checks unless the user explicitly asks.
- If you make changes, report the exact minimal commands the user can run to verify them.
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
