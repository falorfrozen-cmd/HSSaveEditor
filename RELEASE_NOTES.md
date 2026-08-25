# Hero Siege Save Editor v1.1.1

## Fixes

- Separated waypoint unlocks from difficulty unlocks.
- **Unlock Waypoints (Current Difficulty)** now unlocks only the selected
  difficulty tier and preserves the Act 9 campaign-clear marker.
- **Unlock All Difficulties (S10)** now changes only the native Act 9
  difficulty gate and preserves all waypoint values.
- Corrected the current game class IDs: `18 = Jötunn` and
  `19 = Illusionist`.
- Clarified the safe workflow for unlocking every difficulty and waypoint.

## Verification

- All 24 class IDs were compared with the current game class asset names.
- 19 automated save-transformation tests pass.
- A real Season 10 save was audited in memory: the waypoint action did not
  change `difficulty` or `act_9`, and the difficulty action changed only
  `act_9`.

Offline/single-player saves only. Back up saves before editing.
