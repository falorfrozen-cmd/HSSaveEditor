# Hero Siege Save Editor v1.4.0

## What changed

- Renamed the fixed Ether action to `ETHER POINTS`.
- Added an exact-total picker for 100, 200, 300, 400, 500, 600, 700, or 800 Ether Points.
- Existing Ether Tree allocations remain untouched, and choices below the active loadout's allocated points are blocked.
- Ether changes remain staged until `Save Character` is pressed.

## Tested

- Every selectable total is verified against the game's native quest-derived Ether calculation.
- Tests cover repeated application, active-loadout parsing, cancellation, allocation safety, and deferred disk writes.

# Hero Siege Save Editor v1.3.1

## What changed

- Added a confirmed `Delete Character Backups` action.
- Cleanup is restricted to timestamped `herosiegeN.hss` backups created by the editor.
- Current character saves, Stash, `shop.ini`, Ether files, and unrelated backups are never included.
- Linked folders and Windows junctions are not followed during cleanup.

## Tested

- Automated cleanup tests cover both the selected save folder and its direct `hs2saves` folder.
- Tests verify that current saves and every non-character backup type remain untouched.

# Hero Siege Save Editor v1.3.0

## What changed

- Fixed subskill editing for all 24 playable classes.
- Fixed Paladin Holy Hammer.
- Fixed Necromancer skills, including Skeleton Mage.
- Fixed Marksman Gunner Drone and its higher point limits.
- Fixed Jotunn and Illusionist skill detection.
- Old saves made with earlier editor versions are handled more safely.
- The editor now changes only skills that belong to the character and are currently active.

## Tested

- Every class and every current subskill tree was checked.
- All 63 automated tests pass.
- The Windows app was tested with real Marksman, Necromancer, Shaman, Bard and Jotunn saves.

This tool is for offline characters only. Close Hero Siege before editing and keep the automatic backup.
