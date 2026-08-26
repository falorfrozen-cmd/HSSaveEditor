# Hero Siege Save Editor v1.2.8

## Fixes

- Replaced the incorrect universal 50-point subskill limit with the game's exact per-node limits.
- Verified all 222 active Season 10 subskill trees and their 2,220 small-upgrade nodes against the current game build.
- Supports node limits from rank 1 through rank 8; each tree's total is calculated from its own ten nodes.
- Gunner Drone now correctly accepts its two rank-8 upgrades and 56-point total.
- The Max Small Upgrades action now uses each node's real limit and never changes major upgrades.
- Unknown future talent IDs are blocked instead of being written with guessed limits.

## Verification

- All 42 automated tests pass.
- Rebuilt and smoke-tested the standalone Windows executable.

Offline/single-player saves only. Close the game before editing and keep the automatic backup.
