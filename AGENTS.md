# AGENTS.md

`HSSaveEditor` is developed as a submodule of the
[hero-siege-offline-toolkit](https://github.com/falorfrozen-cmd/hero-siege-offline-toolkit)
hub. The rules for working on it live there, not here:

- **Repository-wide guidance:** [`../AGENTS.md`](../AGENTS.md) —
  [view on GitHub](https://github.com/falorfrozen-cmd/hero-siege-offline-toolkit/blob/main/AGENTS.md)
- **This module's guide:** [`../docs/submodules/HSSaveEditor/instructions.md`](../docs/submodules/HSSaveEditor/instructions.md) —
  [view on GitHub](https://github.com/falorfrozen-cmd/hero-siege-offline-toolkit/blob/main/docs/submodules/HSSaveEditor/instructions.md)

Read both before changing anything. The module guide is not optional
background: it carries the architecture, entry points, test commands, build and
packaging steps, and the record of approaches already tried and ruled out, and
several of its requirements are invisible in the code itself.

**Do not add rules to this file.** Module rules belong in that `instructions.md`
and repository-wide rules in the hub's `AGENTS.md`, so there is only ever one
copy to keep true. This file is a signpost.

## If you only have this repository

Those relative paths resolve inside a full toolkit checkout, where this module
sits next to the hub's `docs/`. In a standalone clone they do not — use the
GitHub links above, and clone the hub alongside this repository if you are going
to do real work, since several modules also build against `hs-game-sdk/` from it.

Three rules matter too much to leave behind a link you might not follow:

### Never commit decompiled or disassembled game source

Reading the game's own script bodies locally (Ghidra, IDA, UndertaleModTool,
dnSpy) to understand a mechanism is legitimate research. Committing that output
is not — **and the rule covers this repository's own remote, not just the hub.**
No GML script bodies, decompiled bytecode, decompiler listings or exports, in
any tracked file, commit message, comment, issue or pull request.

What is fine, because it documents interoperability rather than the game's
expression: object/script/room/sprite/sound names and their indices, measured
runtime behaviour (what a call does, what it reads or writes, crash signatures,
before/after values), our own code that reacts to it, and the offsets and
calling conventions needed to hook or read memory. Paraphrase mechanisms in your
own words; never paste the script text. The full rule, including the artifact
paths `.gitignore` blocks as a backstop, is in the hub's `AGENTS.md`.

### Documentation is part of the change, not a follow-up

When a change touches features, workflows, architecture or dependencies, update
the `README.md`, the module guide, and any affected docs in the same change.
A pull request that leaves them stale is unfinished.

### Every piece of work has an issue on the "Hero Siege Tools" project

The owner tracks every repository in this toolkit, this one included, from one
GitHub project board: **"Hero Siege Tools"**, user project 1 of
`falorfrozen-cmd`. Before starting work, find or open an issue for it in this
repository, give its title a type prefix (`[Bug]`, `[QoL]`, `[Mod]`,
`[Adjustment]`, `[Research]`, `[Tooling]`, `[Docs]`), and **add it to that
project with a Status** (`Todo` when filed, `In Progress` when work starts)
in the same step — an issue that is not on the board, or sits on it with no
Status, is invisible to the owner. From the root of a hub checkout,
`py -3 tools/issue_board.py move falorfrozen-cmd/HSSaveEditor <n> "<Status>"`
does both; otherwise `gh issue create --project "Hero Siege Tools"` and set
the Status on the board. If you cannot edit the project, say so in your report
and on the issue instead of reporting it tracked. The full rule is the hub
`AGENTS.md` § "Every Piece of Work Belongs to an Issue on the Board".
