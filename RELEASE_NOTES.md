# Hero Siege Save Editor v1.2.6

## New

- Added safe per-skill subskill editing: distribute up to 50 points across small upgrades and select one major upgrade.
- Added conversion of existing offline characters to Odyssey without changing their level, items, talents, or quest progress.
- Added native Season 10 charm-slot and Ether Point tools.

## Improved

- Simplified the main interface, button names, save messages, confirmations, and subskill explanations.
- Removed internal talent and node IDs from the normal subskill interface.
- Kept automatic timestamped backups while making save results easier to understand.
- Reads current game talent translations to resolve skills instead of relying on one fixed class layout.

## Fixes

- Waypoint unlocking no longer unlocks difficulties.
- Difficulty unlocking no longer changes waypoint progress.
- Corrected the Jötunn and Illusionist class mapping.
- Major subskill upgrades are written directly at their required rank while unselected major upgrades remain disabled.

## Verification

- All 31 automated save-transformation tests pass.
- The standalone Windows executable was rebuilt from the v1.2.6 source.

Offline/single-player saves only. Close the game before editing and keep the automatic backup.
