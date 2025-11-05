# Repository Guidelines

This guide applies to the entire repository tree. If a deeper directory contains its own AGENTS.md, that file takes precedence. For detailed logging, style, and exception handling, prefer CODING.md when present.

## Project Structure & Module Organization
- `src/` — application code, grouped by domain (e.g., `src/editor/`, `src/importer/`).
- `tests/` — unit/integration tests mirroring `src/` paths.
- `assets/` — static media (sample photos, icons); do not embed secrets.
- `scripts/` — repeatable CLI tasks; keep idempotent.
- `docs/` — architecture notes and ADRs.

## Build, Test, and Development Commands
Use the toolchain that exists in this repo (check `package.json`, `pyproject.toml`, or `*.sln`). Examples:
- Node: `npm ci` · `npm run build` · `npm test` · `npm run dev`
- Python: install (`uv/poetry/pip`) then `pytest` · run: `python -m photostudio`
- .NET: `dotnet restore` · `dotnet build` · `dotnet test` · `dotnet run`

## Coding Style & Naming Conventions
- Identifier stability: do not rename public functions/classes/exports without discussion.
- Comments for every class/method/function must be written in Korean. Example (Python): `# 사용자의 세션을 초기화한다.`
- Encoding: UTF-8 for all source and docs.
- Naming: snake_case (Python functions), camelCase (JS/TS functions), PascalCase (classes), kebab-case for web asset filenames unless stack dictates otherwise.
- Run configured formatters/linters (e.g., `black`/`ruff`, `eslint`/`prettier`) using repo settings.

## Testing Guidelines
- Place tests under `tests/`, mirroring `src/` (e.g., `tests/editor/test_crop.py`, `__tests__/editor/crop.test.ts`).
- Add tests for new/changed code and for bug regressions.
- Aim for meaningful coverage; keep tests fast and deterministic.
- Run the stack-appropriate test command before pushing.

## Commit & Pull Request Guidelines
- Prefer Conventional Commits: `feat: …`, `fix: …`, `docs: …`, `refactor: …`.
- PRs must include: clear description, linked issues, screenshots for UI changes, and repro steps for bugfixes.
- Keep diffs focused; avoid unrelated refactors.

## Security & Configuration Tips
- Never commit secrets; use `.env.local`. Document required vars in `.env.example`.
- Emit useful console debug messages to trace failures; follow CODING.md for verbosity/format.

## Agent-Specific Instructions
- Respect this AGENTS.md; deeper files override locally.
- Scan for existing patterns before large edits; update docs/tests alongside code changes.
