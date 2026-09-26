# Hero Siege Save Editor v1.4.2

## What changed

- Fixed: a slot whose character was deleted in the game could not be used again. Hero Siege empties the slot's save file when you delete a character, and the editor only answered "This save slot is empty". Opening such a slot now asks whether to start a new character there. On yes the editor backs up the empty file, writes the same blank character the game keeps in a slot that was never played, and opens it for editing. Copying another slot's file over it by hand is no longer needed.
- The save list shows these slots as `Empty slot - open to start a new character` instead of `Empty / unsupported`, and the character count at the top no longer counts empty or unreadable slots as characters.
- No other behaviour changed.

## Tested

- All 98 automated tests pass, including 8 new ones for emptied slots.
- The blank character decodes to exactly the text of the file the game writes into an unused slot, and an emptied slot is left untouched unless you confirm.

This tool is for offline/single-player characters only. Close Hero Siege before editing and keep the automatic backup.

# Hero Siege Save Editor v1.4.1

## What changed

- Fixed: the editor refused to open the Ether state with "Ether quest progress produced a fractional point total" when an Ether quest chain sat at an odd stage (for example a Wormhole chain at 7 after an Inferno challenge run). The game floors each chain's stage before awarding points, so a half-finished quest simply pays nothing yet; the editor now does the same instead of stopping.
- No other behaviour changed. Ether totals, presets and staged saves work as in 1.4.0.

## Tested

- All 90 automated tests pass, including a new one for odd quest stages.
- The point formula was checked against the game's own StatEtherPoints routine.

This tool is for offline/single-player characters only. Close Hero Siege before editing and keep the automatic backup.

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
