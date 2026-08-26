# Hero Siege Save Editor

A Windows save editor for offline Hero Siege character `.hss` files, presented in a responsive Season 10-inspired Character Save Forge interface.

The editor can load local character saves, edit common character fields, update shared `shop.ini` values such as gold/professions, unlock Season 10 waypoints and difficulties, set a controlled total of 800 Ether Points, and directly edit each active skill's small-node allocation plus its selected major node. It also creates a backup before saving.

## Download

For normal use, download the latest release ZIP from the GitHub Releases page and run:

```text
HeroSiegeSaveEditor.exe
```

Python is not required for the `.exe` release.

## Important Notice

This editor is intended for offline/single-player character saves only.

Do not use it with multiplayer, online characters, leaderboards, trading, or anti-cheat protected modes.

The game must be fully closed before opening, editing, or saving a character file. If the game is still running, it may overwrite your changes or keep the save file locked.

## Features

- Hero Siege-inspired dark forge theme with a procedural rune header, responsive action grid, compact character vault, and scroll-safe content panel.
- Loads Hero Siege character `.hss` files.
- Shows save slots in numeric order.
- Edits character name, class, level, hero level, experience, gold, wormhole level, and professions.
- Reads/writes gold and profession values through `hs2saves/shop.ini`, matching the way Hero Siege stores those shared values.
- Shows class names instead of class numbers.
- Unlocks all Season 10 act/zone waypoints only for the currently selected difficulty, including Act 9 and the expanded zone slots, without marking the Act 9 campaign as cleared.
- Unlocks Normal, Nightmare, Hell, and Inferno through the native Act 9 campaign-clear gate without changing the selected difficulty or waypoint table.
- Unlocks the complete native 30-cell charm grid by completing Season 10's `Light of Dawn` reward state (`fallOfDarkness|4`). Legacy synthetic `charmSlot` fields from older editor builds are removed automatically.
- Sets the character to exactly 800 total earned Ether Points through the game's nine native Ether quest-chain progress records.
- Preserves already allocated nodes; the displayed unspent balance is therefore `800 - allocated nodes`.
- Preserves every existing Ether Tree node allocation in the separate `etherN.hss` sidecar.
- Accepts the game's expanded Ether node IDs without a hard-coded upper limit, so newer valid sidecars remain readable after the tree grows.
- Reads the installed game's current talent/subtalent translation tables and resolves allocated active skills in the current talent loadout.
- Converts an existing local character to Odyssey by enabling the game's native `soloselffound` flag while preserving level, equipment, talents and quest progress.
- Opens a per-skill subskill editor for the current talent loadout. Each of the ten small nodes (`s1-s10`) uses its own game-verified rank cap (1-8 depending on the tree/node); the editor shows the correct total capacity for that skill. Existing out-of-range saved ranks are preserved unless the player changes them.
- Lets the player choose one mutually exclusive large/special node (`s11-s14`); the selected node is written directly at 3/3 and the other large nodes for that skill are cleared.
- Does not depend on the in-game unspent-point counter. The chosen small and major ranks are written directly to the save, so no refund/max round trip is required.
- Falls back to existing saved trees instead of guessing when the current game tables cannot be located or aligned.
- Saves with automatic timestamped backup.
- Standalone Windows `.exe` build available.

## How To Use

1. Close Hero Siege completely.
2. Run `HeroSiegeSaveEditor.exe`.
3. Select a character save from the left list.
4. Edit the fields you want.
5. Press `Save Character`.
6. Start the game again.

Backups are created next to the edited save file.

Gold and profession changes are saved to `shop.ini` in the same save folder. The editor finds it automatically.

Difficulty and waypoint unlocks are intentionally separate. To unlock every
difficulty and then every waypoint, unlock all difficulties first, select and
save the character on Inferno in-game, then run **Unlock Waypoints (Current
Difficulty)** once. The Inferno waypoint tier also covers the lower difficulties.

## Steam Deck / Proton Notes

If a slot appears as `Empty / unsupported`, that file is not a readable character save for this editor. It may be an empty character slot, a Steam Cloud placeholder, or a different folder than the one the game actually uses.

On Steam Deck, make sure the selected folder belongs to the same Proton prefix/account that launches Hero Siege.

## Build From Source

Python 3.13 was used for the current build.

Install PyInstaller:

```powershell
python -m pip install pyinstaller
```

Build:

```powershell
python -m PyInstaller --onefile --windowed --name HeroSiegeSaveEditor hs_save_editor.py
```

The output will be:

```text
dist/HeroSiegeSaveEditor.exe
```

## Files

- `hs_save_editor.py` - source code.
- `test_hs_save_editor.py` - Season 10 save transformation and round-trip tests.
- `README.md` - usage, safety, and build documentation.
- `dist/HeroSiegeSaveEditor.exe` - generated executable after building locally.
