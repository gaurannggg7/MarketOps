# CLAUDE.md

Follow the shared engineering instructions in [AGENTS.md](AGENTS.md); they apply to Claude Code
unchanged. The product/architecture specification is [BUILD_PLAN.md](BUILD_PLAN.md) and the live
status, gate evidence, and continuation steps are in [docs/progress.md](docs/progress.md).

Claude-specific notes:

- Never `git push` without the repository owner's explicit permission in chat (a local
  `.git/hooks/pre-push` guard enforces this on the original machine).
- Use `make help` to discover commands; prefer them over ad-hoc invocations so recorded evidence
  matches what CI runs.
