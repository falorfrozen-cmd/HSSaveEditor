import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import hs_save_editor as editor


SAMPLE_SAVE = """[4]
questlog_chain0="tutorial|4"
questlog_diff0="0.000000"
[0]
name="Test Hero"
class="1.000000"
difficulty="1.000000"
hell_subdifficulty="5.000000"
act_1="0.000000"
zone1,0="0.000000"
[inventory]
item_0=""
"""


def sample_save_for_class(
    class_id: int,
    *,
    loadout_index: int = 0,
    allocated_talent_ids: tuple[int, ...] = (),
) -> str:
    text = SAMPLE_SAVE.replace('class="1.000000"', f'class="{class_id}.000000"')
    text = editor.set_ini_value(text, "0", "talent_loadout", str(loadout_index), "number")
    for talent_id in allocated_talent_ids:
        text = editor.set_ini_value(
            text,
            f"talent_loadout_{loadout_index}",
            f"talent_{talent_id}",
            "1",
            "number",
        )
    return text


class Season10ProgressTests(unittest.TestCase):
    def test_class_ids_match_current_game_assets(self):
        self.assertEqual(editor.CLASS_ID_TO_NAME[18], "Jötunn")
        self.assertEqual(editor.CLASS_ID_TO_NAME[19], "Illusionist")

    def test_fractional_character_class_is_rejected(self):
        malformed = SAMPLE_SAVE.replace('class="1.000000"', 'class="7.500000"')
        with self.assertRaisesRegex(ValueError, "Unsupported character class value"):
            editor.character_class_id(malformed)

    def test_s10_talent_id_map_covers_all_classes_without_duplicates(self):
        self.assertEqual(set(editor.S10_CLASS_TALENT_KEYS), set(range(1, 25)))
        self.assertEqual(sum(map(len, editor.S10_CLASS_TALENT_KEYS.values())), 432)
        for class_id, keys in editor.S10_CLASS_TALENT_KEYS.items():
            with self.subTest(class_id=class_id):
                self.assertEqual(len(keys), 18)
                self.assertEqual(len({key.casefold() for key in keys}), 18)

    def test_native_talent_blocks_swap_jotunn_and_illusionist(self):
        self.assertEqual(editor.class_talent_block_start(18), 326)
        self.assertEqual(editor.class_talent_block_start(19), 308)
        native_ids = {
            editor.class_talent_block_start(class_id) + offset
            for class_id in range(1, 25)
            for offset in range(18)
        }
        self.assertEqual(native_ids, set(range(2, 434)))

    def test_all_24_native_talent_maps_match_audited_exe_snapshot(self):
        payload = "\n".join(
            f"{class_id}:{','.join(editor.S10_CLASS_TALENT_KEYS[class_id])}"
            for class_id in sorted(editor.S10_CLASS_TALENT_KEYS)
        )
        self.assertEqual(
            hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            "783b3ebaf61f7a7cf32269daef24faade75c6aef1fa85bdcab667debf08dbc0f",
        )

    def test_verified_subtalent_ids_match_current_get_subtalent_info_switch(self):
        expected_by_class = {
            1: {7, 10, 11, 12, 13, 14, 16, 17, 18},
            2: {20, 22, 23, 29, 30, 32, 33, 34, 35, 36, 37},
            3: {38, 39, 40, 41, 44, 46, 47, 48, 50, 52, 53, 55},
            4: {56, 58, 59, 60, 61, 63, 65, 66, 68, 71, 73},
            5: {74, 75, 76, 79, 82, 83, 84, 85, 87, 89, 90},
            6: {92, 93, 95, 100, 101, 103, 108, 109},
            7: {110, 112, 113, 114, 116, 117, 118, 120, 122, 125, 127},
            8: {128, 129, 131, 132, 135, 137, 139, 140, 143, 145},
            9: {146, 148, 149, 150, 152, 155, 158, 161, 162},
            10: {164, 165, 166, 167, 172, 173, 175, 176, 177, 180},
            11: {182, 185, 186, 187, 190, 191, 192, 198},
            12: {200, 201, 204, 207, 208, 209, 215},
            13: {218, 219, 220, 221, 222, 224, 226, 227, 229, 230, 232, 235},
            14: {236, 237, 239, 240, 242, 244, 245, 246, 250, 253},
            15: {254, 255, 257, 259, 261, 263, 264, 265, 269, 271},
            16: {272, 276, 281, 282, 283, 287, 288, 289},
            17: {290, 292, 293, 296, 299, 301, 304, 305},
            18: {326, 327, 329, 332, 334, 336, 337, 340, 341},
            19: {308, 315, 317, 318, 325},
            20: {344, 346, 348, 352, 355, 356, 358, 361},
            21: {362, 363, 371, 372, 375, 376, 377, 379},
            22: {380, 383, 386, 387, 390, 396},
            23: {398, 400, 402, 406, 407, 409, 412, 415},
            24: {416, 417, 418, 420, 421, 422, 424, 425, 426, 428, 429, 430, 433},
        }
        self.assertEqual(sum(map(len, expected_by_class.values())), 222)
        for class_id, expected in expected_by_class.items():
            block_start = editor.class_talent_block_start(class_id)
            actual = {
                talent_id
                for talent_id in editor.S10_VERIFIED_SUBTALENT_IDS
                if block_start <= talent_id < block_start + 18
            }
            with self.subTest(class_id=class_id):
                self.assertEqual(actual, expected)

    def test_remapped_classes_use_native_active_skill_ids(self):
        expected = {
            1: {"charge": 11, "odinsFury": 7, "seismicSlam": 10, "monsterThrow": 13,
                "zeal": 12, "ymirsChampion": 14, "whirlwind": 17, "shockwave": 16, "berserk": 18},
            4: {"buckshot": 56, "explosiveBarrel": 58, "cannonball": 59, "explosiveBullet": 60,
                "powderTrail": 61, "bombBarrage": 63, "torrent": 65, "freezeChainShot": 66,
                "parrot": 68, "anchorSwing": 71, "landAhoy": 73},
            6: {"moonshineMolotov": 92, "pipeBombs": 93, "tireFire": 95, "pickupRaid": 100,
                "chainsawSlash": 101, "chainsawMassacre": 103, "rogueChainsaw": 108,
                "treeTrunkTriumph": 109},
            7: {"boneShred": 110, "meatBomb": 112, "poisonBreath": 113, "boneSpear": 114,
                "boneSpirit": 116, "corpseExplosion": 117, "poisonNova": 118,
                "raiseSkeletonWarrior": 120, "raiseSkeletonMage": 122,
                "summonDamnedLegion": 125, "summonVengefulSpirit": 127},
            8: {"quickSlash": 128, "battleGlance": 129, "smokeBomb": 131, "shurikenThrow": 132,
                "explosiveKunai": 135, "bladeBarrier": 137, "omnislash": 139,
                "explodingBolas": 140, "shadowStep": 143, "empiresSlash": 145},
            9: {"vengeance": 146, "lightningFury": 148, "holyShockAura": 149, "divineStorm": 150,
                "ballLightning": 152, "holyBolt": 155, "holyHammer": 158,
                "fistOfTheHeavens": 161, "holyNova": 162},
            12: {"boneFragments": 200, "impale": 201, "boneStorm": 204, "spinalTap": 207,
                 "boneBarrage": 208, "bloodBolts": 209, "bloodSurge": 215},
            13: {"tectonicBoulder": 218, "twisters": 219, "rockFragments": 220, "earthBind": 221,
                 "tornado": 222, "meteorStorm": 224, "fissures": 226, "earthTotem": 227,
                 "stormTotem": 229, "spiritWolves": 230, "fireTotem": 232, "chaosTotem": 235},
        }
        for class_id, skill_ids in expected.items():
            keys = editor.S10_CLASS_TALENT_KEYS[class_id]
            block_start = editor.class_talent_block_start(class_id)
            for skill_key, expected_id in skill_ids.items():
                with self.subTest(class_id=class_id, skill=skill_key):
                    self.assertEqual(block_start + keys.index(skill_key), expected_id)

    def test_character_and_shop_fields_still_write_expected_sections(self):
        character = SAMPLE_SAVE
        shop = editor.default_shop_ini_text()
        for spec in editor.CHARACTER_FIELDS:
            if editor.is_shop_backed_field(spec):
                continue
            value = "Shaman" if spec.key == "class" else "25"
            character = editor.set_field_value(character, spec, value)
        self.assertEqual(editor.get_ini_value(character, "0", "class"), "13.000000")
        self.assertEqual(editor.get_ini_value(character, "0", "level"), "25.000000")

        for spec in editor.PROFESSION_FIELDS + [editor.CHARACTER_FIELDS[5]]:
            shop = editor.set_field_value(shop, spec, "77")
            self.assertEqual(editor.get_ini_value(shop, spec.section, spec.key), "77.000000")
            for extra_key in spec.extra_keys:
                self.assertEqual(editor.get_ini_value(shop, spec.section, extra_key), "77.000000")

    def test_convert_character_to_odyssey_only_enables_native_flag(self):
        normal = editor.set_ini_value(SAMPLE_SAVE, "0", "soloselffound", "0", "number")
        result = editor.convert_character_to_odyssey(normal)
        self.assertFalse(editor.is_odyssey_character(normal))
        self.assertTrue(editor.is_odyssey_character(result))
        self.assertEqual(editor.get_ini_value(result, "0", "soloselffound"), "1.000000")
        self.assertEqual(editor.get_ini_value(result, "0", "name"), "Test Hero")
        self.assertEqual(editor.get_ini_value(result, "0", "class"), "1.000000")
        self.assertEqual(editor.get_ini_value(result, "0", "level"), "")

    def test_convert_character_to_odyssey_is_idempotent(self):
        odyssey = editor.set_ini_value(SAMPLE_SAVE, "0", "soloselffound", "1", "number")
        self.assertEqual(editor.convert_character_to_odyssey(odyssey), odyssey)

    def test_waypoints_cover_current_s10_difficulty_without_clearing_act_9(self):
        result = editor.unlock_all_waypoints(SAMPLE_SAVE)
        self.assertEqual(editor.get_ini_value(result, "0", "difficulty"), "1.000000")
        for act in range(1, 9):
            self.assertEqual(editor.get_ini_value(result, "0", f"act_{act}"), "2.000000")
        self.assertEqual(editor.get_ini_value(result, "0", "act_9"), "")
        for act in range(1, 10):
            for zone in range(10):
                self.assertEqual(editor.get_ini_value(result, "0", f"zone{act},{zone}"), "2.000000")

    def test_waypoint_unlock_preserves_higher_progress(self):
        existing = editor.set_ini_value(SAMPLE_SAVE, "0", "act_1", "3", "number")
        existing = editor.set_ini_value(existing, "0", "act_9", "1", "number")
        existing = editor.set_ini_value(existing, "0", "zone1,0", "4", "number")
        result = editor.unlock_all_waypoints(existing)
        self.assertEqual(editor.get_ini_value(result, "0", "act_1"), "3.000000")
        self.assertEqual(editor.get_ini_value(result, "0", "act_9"), "1.000000")
        self.assertEqual(editor.get_ini_value(result, "0", "zone1,0"), "4.000000")

    def test_difficulty_unlock_only_changes_act_9_campaign_gate(self):
        result = editor.unlock_all_difficulties(SAMPLE_SAVE)
        self.assertEqual(editor.get_ini_value(result, "0", "difficulty"), "1.000000")
        self.assertEqual(editor.get_ini_value(result, "0", "hell_subdifficulty"), "5.000000")
        self.assertEqual(editor.get_ini_value(result, "0", "act_9"), "4.000000")
        self.assertEqual(editor.get_ini_value(result, "0", "act_1"), "0.000000")
        self.assertEqual(editor.get_ini_value(result, "0", "zone1,0"), "0.000000")

    def test_charm_unlock_preserves_unrelated_quest_slots(self):
        result = editor.unlock_charm_slots(SAMPLE_SAVE)
        entries = editor.quest_chain_entries(result)
        self.assertEqual(entries[0], ("tutorial", 4))
        self.assertEqual(entries[1], ("fallOfDarkness", 4))
        self.assertEqual(editor.get_ini_value(result, "4", "questlog_diff1"), "3.000000")
        self.assertEqual(editor.get_ini_value(result, "4", "questlog_sub_diff1"), "0.000000")
        self.assertEqual(editor.get_ini_value(result, "0", "charmSlot"), "")

    def test_charm_unlock_matches_known_good_s10_state_and_removes_legacy_key(self):
        existing = editor.set_ini_value(SAMPLE_SAVE, "4", "questlog_chain7", "fallOfDarkness|2", "text")
        existing = editor.set_ini_value(existing, "0", "charmSlot", "1", "number")
        result = editor.unlock_charm_slots(existing)
        self.assertEqual(editor.quest_chain_entries(result)[7], ("fallOfDarkness", 4))
        self.assertEqual(result.count("fallOfDarkness|"), 1)
        self.assertEqual(editor.get_ini_value(result, "0", "charmSlot"), "")

    def test_charm_unlock_preserves_progress_beyond_native_final_stage(self):
        existing = editor.set_ini_value(SAMPLE_SAVE, "4", "questlog_chain7", "fallOfDarkness|6", "text")
        result = editor.unlock_charm_slots(existing)
        self.assertEqual(editor.quest_chain_entries(result)[7], ("fallOfDarkness", 6))

    def test_remove_ini_key_is_scoped_to_requested_section(self):
        existing = editor.set_ini_value(SAMPLE_SAVE, "0", "charmSlot", "1", "number")
        existing = editor.set_ini_value(existing, "4", "charmSlot", "keep", "text")
        result = editor.remove_ini_key(existing, "0", "charmSlot")
        self.assertEqual(editor.get_ini_value(result, "0", "charmSlot"), "")
        self.assertEqual(editor.get_ini_value(result, "4", "charmSlot"), "keep")

    def test_hss_roundtrip_after_progress_edits(self):
        edited = editor.unlock_charm_slots(editor.unlock_all_difficulties(SAMPLE_SAVE))
        encoded = editor.encode_hss_text(edited)
        self.assertEqual(editor.decode_hss_bytes(encoded), edited)

    def test_unlock_all_s10_ether_points_uses_native_final_quest_progress(self):
        result = editor.unlock_all_ether_points(SAMPLE_SAVE)
        entries = list(editor.quest_chain_entries(result).values())
        self.assertIn(("tutorial", 4), entries)
        for chain_name, final_progress, _difficulty in editor.S10_ETHER_QUEST_CHAINS:
            self.assertIn((chain_name, final_progress), entries)
        self.assertEqual(len([entry for entry in entries if entry[0].startswith("ethering")]), 9)
        self.assertEqual(editor.ether_earned_points(result), 87)

    def test_unlock_all_s10_ether_points_preserves_higher_progress_and_duplicates(self):
        existing = editor.set_ini_value(SAMPLE_SAVE, "4", "questlog_chain5", "etheringHell|8", "text")
        existing = editor.set_ini_value(existing, "4", "questlog_chain9", "etheringHell|2", "text")
        result = editor.unlock_all_ether_points(existing)
        entries = editor.quest_chain_entries(result)
        self.assertEqual(entries[5], ("etheringHell", 8))
        self.assertEqual(entries[9], ("etheringHell", 6))

    def test_grant_400_available_ether_points_accounts_for_allocated_nodes(self):
        result = editor.grant_available_ether_points(SAMPLE_SAVE, 400, allocated_nodes=1)
        entries = list(editor.quest_chain_entries(result).values())
        self.assertIn(("etheringWormhole", 650), entries)
        self.assertEqual(editor.ether_earned_points(result), 401)
        self.assertEqual(editor.ether_earned_points(result) - 1, 400)

    def test_grant_available_ether_points_is_stable_when_reapplied(self):
        first = editor.grant_available_ether_points(SAMPLE_SAVE, 400, allocated_nodes=7)
        second = editor.grant_available_ether_points(first, 400, allocated_nodes=7)
        self.assertEqual(editor.ether_earned_points(second), 407)
        wormhole = [progress for name, progress in editor.quest_chain_entries(second).values() if name == "etheringWormhole"]
        self.assertEqual(wormhole, [662])

    def test_set_total_ether_points_to_800(self):
        result = editor.set_total_ether_points(SAMPLE_SAVE, 800)
        self.assertEqual(editor.ether_earned_points(result), 800)
        wormhole = [progress for name, progress in editor.quest_chain_entries(result).values() if name == "etheringWormhole"]
        self.assertEqual(wormhole, [1448])

    def test_set_total_ether_points_normalizes_artificially_high_non_wormhole_progress(self):
        existing = editor.set_ini_value(SAMPLE_SAVE, "4", "questlog_chain8", "etheringChallenge|250", "text")
        result = editor.set_total_ether_points(existing, 800)
        self.assertEqual(editor.ether_earned_points(result), 800)
        challenge = [
            progress
            for name, progress in editor.quest_chain_entries(result).values()
            if name == "etheringChallenge"
        ]
        self.assertEqual(challenge, [4])

    def test_s10_ether_sidecar_decodes_observed_node_payload(self):
        observed = b"eyJ2ZXJzaW9uIjoxLCJsb2Fkb3V0cyI6W3sibm9kZXMiOls0Nl19LHt9LHt9LHt9LHt9LHt9LHt9LHt9XX0=\x00"
        data = editor.decode_ether_bytes(observed)
        self.assertEqual(editor.ether_loadout_nodes(data, 0), [46])
        self.assertEqual(editor.decode_ether_bytes(editor.encode_ether_data(data)), data)

    def test_s10_ether_loadout_preserves_order_and_duplicate_node_ids(self):
        data = editor.set_ether_loadout_nodes(editor.default_ether_data(), 2, [46, 46, 0, 577])
        self.assertEqual(editor.ether_loadout_nodes(data, 2), [46, 46, 0, 577])
        self.assertEqual(editor.parse_ether_node_ids("46, 46; 0 577"), [46, 46, 0, 577])

    def test_ether_sidecar_preserves_future_node_ids_without_a_fixed_ceiling(self):
        data = editor.set_ether_loadout_nodes(editor.default_ether_data(), 0, [577, 578, 999])
        encoded = editor.encode_ether_data(data)
        self.assertEqual(editor.ether_loadout_nodes(editor.decode_ether_bytes(encoded), 0), [577, 578, 999])

    def test_ether_node_ids_reject_negative_and_fractional_values(self):
        with self.assertRaises(editor.EtherFormatError):
            editor.parse_ether_node_ids("-1")
        invalid = editor.default_ether_data()
        invalid["loadouts"][0]["nodes"] = [1.5]
        with self.assertRaises(editor.EtherFormatError):
            editor.normalize_ether_data(invalid)

    def test_s10_ether_sidecar_matches_character_slot(self):
        path = Path(r"C:\save\herosiege19.hss")
        self.assertEqual(editor.ether_path_for_character(path), Path(r"C:\save\ether19.hss"))

    def test_max_small_subtalents_only_changes_s1_through_s10(self):
        original = {
            "t220": {
                "s1": 2.0,
                "s5": 1.0,
                "s11": 3.0,
                "s12": 0.0,
                "s14": 2.0,
            }
        }
        encoded = base64.b64encode(json.dumps(original, separators=(",", ":")).encode()).decode()
        save = sample_save_for_class(13, loadout_index=1, allocated_talent_ids=(220,))
        save = editor.set_ini_value(save, "talent_loadout_1", "subtalents", encoded, "text")

        result, tree_count, changed_nodes = editor.max_small_subtalent_nodes(save)
        decoded = editor.decode_subtalent_map(result, 1)

        self.assertEqual(tree_count, 1)
        self.assertEqual(changed_nodes, 10)
        for node_id in editor.S10_SMALL_SUBTALENT_NODE_IDS:
            self.assertEqual(decoded["t220"][f"s{node_id}"], 5.0)
        for node_id in editor.S10_MAJOR_SUBTALENT_NODE_IDS:
            key = f"s{node_id}"
            self.assertEqual(decoded["t220"].get(key), original["t220"].get(key))

    def test_max_small_subtalents_uses_gunner_drone_node_caps(self):
        original = {"t55": {"s11": 3.0}}
        save = sample_save_for_class(3, allocated_talent_ids=(55,))
        save = editor.set_ini_value(
            save, "talent_loadout_0", "subtalents", editor.encode_base64_json(original), "text"
        )

        result, tree_count, changed_nodes = editor.max_small_subtalent_nodes(save)
        nodes = editor.decode_subtalent_map(result, 0)["t55"]

        self.assertEqual((tree_count, changed_nodes), (1, 10))
        self.assertEqual(tuple(int(nodes[f"s{i}"]) for i in range(1, 11)), (8, 8, 5, 5, 5, 5, 5, 5, 5, 5))
        self.assertEqual(nodes["s11"], 3.0)

    def test_every_verified_subtalent_tree_has_ten_positive_node_caps(self):
        self.assertEqual(len(editor.S10_VERIFIED_SUBTALENT_IDS), 222)
        payload = "\n".join(
            f"{talent_id}:" + ",".join(map(str, editor.small_subtalent_node_caps(talent_id)))
            for talent_id in sorted(editor.S10_VERIFIED_SUBTALENT_IDS)
        )
        self.assertEqual(
            hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            "06ca4f7bb2155aae90a330538b69e22c9b7daff125b9a39e86b4662ea3444cef",
        )
        for talent_id in editor.S10_VERIFIED_SUBTALENT_IDS:
            with self.subTest(talent_id=talent_id):
                caps = editor.small_subtalent_node_caps(talent_id)
                self.assertEqual(len(caps), 10)
                self.assertTrue(all(isinstance(cap, int) and cap > 0 for cap in caps))

    def test_major_subtalent_selection_rejects_corrupt_or_conflicting_nodes(self):
        self.assertIsNone(editor.selected_major_subtalent_node({}))
        self.assertEqual(editor.selected_major_subtalent_node({"s13": 3.0}), 13)
        with self.assertRaisesRegex(ValueError, "invalid rank"):
            editor.selected_major_subtalent_node({"s11": "broken"})
        with self.assertRaisesRegex(ValueError, "More than one major"):
            editor.selected_major_subtalent_node({"s11": 3.0, "s12": 3.0})

    def test_max_small_subtalents_normalizes_to_five_each_and_preserves_other_loadouts(self):
        active = {"t220": {"s2": 7.0, "s13": 3.0}}
        inactive = {"t99": {"s1": 1.0, "s11": 3.0}}
        save = sample_save_for_class(13, allocated_talent_ids=(220,))
        save = editor.set_ini_value(
            save, "talent_loadout_0", "subtalents", editor.encode_base64_json(active), "text"
        )
        save = editor.set_ini_value(
            save, "talent_loadout_1", "subtalents", editor.encode_base64_json(inactive), "text"
        )

        result, tree_count, changed_nodes = editor.max_small_subtalent_nodes(save)

        self.assertEqual(tree_count, 1)
        self.assertEqual(changed_nodes, 10)
        active_result = editor.decode_subtalent_map(result, 0)["t220"]
        self.assertTrue(all(active_result[f"s{node_id}"] == 5.0 for node_id in range(1, 11)))
        self.assertEqual(active_result["s13"], 3.0)
        self.assertEqual(editor.decode_subtalent_map(result, 1), inactive)

    def test_max_small_subtalents_does_not_invent_missing_skill_trees(self):
        save = editor.set_ini_value(SAMPLE_SAVE, "0", "talent_loadout", "0", "number")
        save = editor.set_ini_value(save, "talent_loadout_0", "subtalents", "e30=", "text")
        result, tree_count, changed_nodes = editor.max_small_subtalent_nodes(save)
        self.assertEqual(result, save)
        self.assertEqual((tree_count, changed_nodes), (0, 0))

    def test_max_small_subtalents_creates_only_verified_trees_and_never_major_nodes(self):
        original = {"t220": {"s11": 3.0, "s14": 0.0}}
        save = sample_save_for_class(13, allocated_talent_ids=(218, 220))
        save = editor.set_ini_value(
            save, "talent_loadout_0", "subtalents", editor.encode_base64_json(original), "text"
        )

        result, tree_count, changed_nodes = editor.max_small_subtalent_nodes(
            save,
            create_talent_ids={218, 220},
        )
        decoded = editor.decode_subtalent_map(result, 0)

        self.assertEqual(tree_count, 2)
        self.assertEqual(changed_nodes, 20)
        self.assertEqual(decoded["t220"]["s11"], 3.0)
        self.assertEqual(decoded["t220"]["s14"], 0.0)
        self.assertFalse(any(key in decoded["t218"] for key in ("s11", "s12", "s13", "s14")))

    def test_max_small_subtalents_preserves_wrong_class_and_unallocated_trees(self):
        untouched = {"s1": 2.0, "s11": 3.0}
        trees = {"t318": untouched.copy(), "t327": {"s1": 1.0}}
        save = sample_save_for_class(18, allocated_talent_ids=(318, 327))
        save = editor.set_ini_value(
            save, "talent_loadout_0", "subtalents", editor.encode_base64_json(trees), "text"
        )

        result, tree_count, changed_nodes = editor.max_small_subtalent_nodes(save)
        decoded = editor.decode_subtalent_map(result, 0)

        self.assertEqual(tree_count, 1)
        self.assertGreater(changed_nodes, 0)
        self.assertEqual(decoded["t318"], untouched)
        self.assertTrue(all(decoded["t327"][f"s{node_id}"] == 5.0 for node_id in range(1, 11)))

    def test_all_24_classes_can_max_and_apply_every_native_subskill_tree(self):
        for class_id in range(1, 25):
            talent_ids = tuple(sorted(editor.verified_class_subtalent_ids(class_id)))
            save = sample_save_for_class(class_id, allocated_talent_ids=talent_ids)

            maxed, tree_count, _changed_nodes = editor.max_small_subtalent_nodes(
                save,
                create_talent_ids=set(talent_ids),
            )
            maxed_trees = editor.decode_subtalent_map(maxed, 0)
            with self.subTest(class_id=class_id, action="max"):
                self.assertEqual(tree_count, len(talent_ids))
                for talent_id in talent_ids:
                    caps = editor.small_subtalent_node_caps(talent_id)
                    self.assertEqual(
                        tuple(int(maxed_trees[f"t{talent_id}"][f"s{node_id}"]) for node_id in range(1, 11)),
                        caps,
                    )

            allocations = {
                talent_id: (editor.small_subtalent_node_caps(talent_id), 11)
                for talent_id in talent_ids
            }
            applied, applied_count, _changed_nodes = editor.apply_subtalent_allocations(
                maxed,
                allocations,
                loadout_index=0,
                verified_talent_ids=set(talent_ids),
            )
            applied_trees = editor.decode_subtalent_map(applied, 0)
            with self.subTest(class_id=class_id, action="apply"):
                self.assertEqual(applied_count, len(talent_ids))
                self.assertTrue(
                    all(applied_trees[f"t{talent_id}"]["s11"] == 3.0 for talent_id in talent_ids)
                )

    def test_marksman_v126_legacy_trees_do_not_get_maxed_when_skills_are_unallocated(self):
        trees = {
            "t42": {},
            "t54": {},
            "t55": {"s1": 8.0, "s4": 5.0, "s12": 3.0},
        }
        save = sample_save_for_class(
            3,
            allocated_talent_ids=(38, 42, 47, 48, 51, 54, 55),
        )
        save = editor.set_ini_value(
            save, "talent_loadout_0", "subtalents", editor.encode_base64_json(trees), "text"
        )

        result, tree_count, _changed_nodes = editor.max_small_subtalent_nodes(
            save,
            create_talent_ids={38, 47, 48, 55},
        )
        decoded = editor.decode_subtalent_map(result, 0)

        self.assertEqual(tree_count, 4)
        self.assertEqual(decoded["t44"], {})
        self.assertEqual(decoded["t50"], {})
        self.assertTrue(all(f"s{node_id}" in decoded["t55"] for node_id in range(1, 11)))
        self.assertNotIn("t42", decoded)
        self.assertNotIn("t54", decoded)

    def test_apply_subtalent_allocations_writes_small_ranks_and_one_major(self):
        original = {
            "t220": {
                "s1": 5.0,
                "s5": 2.0,
                "s10": 5.0,
                "s11": 3.0,
                "s12": 0.0,
                "s14": 1.0,
            }
        }
        save = sample_save_for_class(13, allocated_talent_ids=(220,))
        save = editor.set_ini_value(
            save, "talent_loadout_0", "subtalents", editor.encode_base64_json(original), "text"
        )

        ranks = (5, 4, 3, 2, 1, 0, 0, 0, 0, 0)
        result, tree_count, changed_nodes = editor.apply_subtalent_allocations(
            save,
            {220: (ranks, 13)},
            loadout_index=0,
            verified_talent_ids={220},
        )
        decoded = editor.decode_subtalent_map(result, 0)

        self.assertEqual(tree_count, 1)
        self.assertGreater(changed_nodes, 0)
        for node_id, rank in enumerate(ranks, start=1):
            if rank:
                self.assertEqual(decoded["t220"][f"s{node_id}"], float(rank))
            else:
                self.assertNotIn(f"s{node_id}", decoded["t220"])
        self.assertEqual(decoded["t220"]["s13"], 3.0)
        self.assertNotIn("s11", decoded["t220"])
        self.assertNotIn("s12", decoded["t220"])
        self.assertNotIn("s14", decoded["t220"])

    def test_apply_subtalent_allocations_does_not_change_unselected_trees(self):
        other_tree = {"s1": 2.0, "s14": 3.0}
        original = {
            "t220": {**{f"s{node_id}": 5.0 for node_id in range(1, 11)}, "s13": 3.0},
            "t221": other_tree.copy(),
        }
        save = sample_save_for_class(13, allocated_talent_ids=(220, 221))
        save = editor.set_ini_value(
            save, "talent_loadout_0", "subtalents", editor.encode_base64_json(original), "text"
        )
        result, _, _ = editor.apply_subtalent_allocations(
            save,
            {220: ((5,) * 10, 12)},
            loadout_index=0,
            verified_talent_ids={220},
        )
        decoded = editor.decode_subtalent_map(result, 0)
        self.assertEqual(decoded["t220"]["s12"], 3.0)
        self.assertNotIn("s13", decoded["t220"])
        self.assertTrue(all(decoded["t220"][f"s{node_id}"] == 5.0 for node_id in range(1, 11)))
        self.assertEqual(decoded["t221"], other_tree)

    def test_apply_subtalent_allocations_allows_distributing_more_than_five_to_a_node(self):
        original = {"t55": {"s1": 7.0, "s2": 2.0, "s13": 3.0}}
        save = sample_save_for_class(3, allocated_talent_ids=(55,))
        save = editor.set_ini_value(
            save, "talent_loadout_0", "subtalents", editor.encode_base64_json(original), "text"
        )

        result, _, _ = editor.apply_subtalent_allocations(
            save,
            {55: ((7, 5, 0, 0, 0, 0, 0, 0, 0, 0), 13)},
            loadout_index=0,
            verified_talent_ids={55},
        )
        decoded = editor.decode_subtalent_map(result, 0)

        self.assertEqual(decoded["t55"]["s1"], 7.0)
        self.assertEqual(decoded["t55"]["s2"], 5.0)
        self.assertEqual(decoded["t55"]["s13"], 3.0)

    def test_apply_subtalent_allocations_allows_rapidfire_style_rank_eight(self):
        original = {"t55": {"s1": 5.0}}
        save = sample_save_for_class(3, allocated_talent_ids=(55,))
        save = editor.set_ini_value(
            save, "talent_loadout_0", "subtalents", editor.encode_base64_json(original), "text"
        )

        result, _, _ = editor.apply_subtalent_allocations(
            save,
            {55: ((0, 8, 5, 5, 5, 5, 5, 5, 5, 2), None)},
            loadout_index=0,
            verified_talent_ids={55},
        )
        self.assertEqual(editor.decode_subtalent_map(result, 0)["t55"]["s2"], 8.0)

    def test_apply_subtalent_allocations_accepts_gunner_drone_full_fifty_six_points(self):
        save = sample_save_for_class(3, allocated_talent_ids=(55,))
        ranks = (8, 8, 5, 5, 5, 5, 5, 5, 5, 5)
        result, _, _ = editor.apply_subtalent_allocations(
            save,
            {55: (ranks, None)},
            loadout_index=0,
            verified_talent_ids={55},
        )
        decoded = editor.decode_subtalent_map(result, 0)["t55"]
        self.assertEqual(sum(int(decoded[f"s{node_id}"]) for node_id in range(1, 11)), 56)

    def test_apply_subtalent_allocations_rejects_rank_above_node_cap(self):
        save = sample_save_for_class(3, allocated_talent_ids=(55,))
        with self.assertRaisesRegex(ValueError, "node s3 allows at most 5"):
            editor.apply_subtalent_allocations(
                save,
                {55: ((8, 8, 6, 5, 5, 5, 5, 5, 5, 5), None)},
                loadout_index=0,
                verified_talent_ids={55},
            )

    def test_steam_library_discovery_supports_custom_drives(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "Steam"
            custom = Path(directory) / "Games"
            (root / "steamapps").mkdir(parents=True)
            (root / "steamapps" / "libraryfolders.vdf").write_text(
                f'"libraryfolders"\n{{\n"1"\n{{\n"path" "{str(custom).replace(chr(92), chr(92) * 2)}"\n}}\n}}',
                encoding="utf-8",
            )
            self.assertIn(custom, editor.steam_library_roots([root]))

    def test_translation_discovery_accepts_an_explicit_game_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            game_root = Path(directory) / "HeroSiege"
            bin_root = game_root / "bin"
            bin_root.mkdir(parents=True)
            talent = bin_root / "translationsTalent.csv"
            subtalent = bin_root / "translationsSubTalent.csv"
            talent.write_text("talent_name_test|Test", encoding="utf-8")
            subtalent.write_text("subTest01|Test", encoding="utf-8")
            with patch.dict("os.environ", {"HERO_SIEGE_DIR": str(game_root)}):
                self.assertEqual(editor.game_translation_file_pair(), (talent, subtalent))

    def test_apply_subtalent_allocations_rejects_unverified_skill(self):
        save = editor.set_ini_value(SAMPLE_SAVE, "0", "talent_loadout", "0", "number")
        with self.assertRaisesRegex(ValueError, "not a verified allocated active skill"):
            editor.apply_subtalent_allocations(
                save,
                {999: ((5,) * 10, 11)},
                loadout_index=0,
                verified_talent_ids={220},
            )

    def test_translation_resolver_aligns_active_skills_inside_eighteen_talent_block(self):
        keys = editor.S10_CLASS_TALENT_KEYS[13]
        talent_text = "\n".join(f"talent_name_{key}|{key}" for key in keys)
        subtalent_text = "\n".join(
            [
                "subShamanTectonicBoulder01|A",
                "subShamanTectonicBoulder14|B",
                "subShamanTornado01|C",
                "subShamanChaosTotem01|D",
            ]
        )
        self.assertEqual(
            editor.active_subtalent_offsets_from_translations("Shaman", talent_text, subtalent_text),
            (0, 4, 17),
        )

    def test_marksman_group_maps_rocket_turret_and_gunner_drone_to_correct_ids(self):
        marksman_keys = editor.S10_CLASS_TALENT_KEYS[3]
        talent_text = "\n".join(f"talent_name_{key}|{key}" for key in marksman_keys)
        subtalent_text = "\n".join(
            [
                "subMarksmanTrickshot01|Trickshot A",
                "subMarksmanArrowTurret01|Arrow Turret A",
                "subMarksmanFragGrenade01|Frag A",
                "subMarksmanRocketTurret01|Rocket A",
                "subMarksmanRocketTurret14|Rocket Major",
                "subMarksmanGunnerDrones01|Drone A",
                "subMarksmanGunnerDrones14|Drone Major",
            ]
        )

        definitions = editor.subtalent_tree_definitions_from_translations(
            "Marksman",
            3,
            talent_text,
            subtalent_text,
        )

        self.assertEqual(
            [(definition.talent_id, definition.skill_name) for definition in definitions],
            [
                (38, "trickShot"),
                (47, "arrowTurret"),
                (48, "fragGrenade"),
                (53, "rocketTurret"),
                (55, "gunnerDrone"),
            ],
        )
        self.assertEqual(definitions[-1].node_names[0], "Drone A")
        self.assertEqual(definitions[-1].small_node_caps, (8, 8, 5, 5, 5, 5, 5, 5, 5, 5))

    def test_paladin_holy_hammer_resolves_to_native_tree_t158(self):
        paladin_keys = editor.S10_CLASS_TALENT_KEYS[9]
        talent_text = "\n".join(f"talent_name_{key}|{key}" for key in paladin_keys)
        subtalent_text = "\n".join(
            [
                "subPaladinHolyHammer01|Anvil Smash",
                "subPaladinHolyHammer14|Hammer Major",
                "subPaladinHolyNova01|Nova Node",
                "subPaladinFistOfTheHeavens01|Fist Node",
            ]
        )

        definitions = editor.subtalent_tree_definitions_from_translations(
            "Paladin",
            9,
            talent_text,
            subtalent_text,
        )

        self.assertEqual(
            [(definition.talent_id, definition.skill_name) for definition in definitions],
            [(158, "holyHammer"), (161, "fistOfTheHeavens"), (162, "holyNova")],
        )
        self.assertEqual(definitions[0].node_names[0], "Anvil Smash")

    def test_jotunn_native_save_resolves_breath_and_portal_subskills(self):
        jotunn_keys = editor.S10_CLASS_TALENT_KEYS[18]
        talent_text = "\n".join(f"talent_name_{key}|{key}" for key in jotunn_keys)
        subtalent_text = "\n".join(
            [
                "subJotunnBreathOfIce01|Cold Breath",
                "subJotunnBreathOfIce14|Breath Major",
                "subJotunnPortalOfIce01|Frozen Portal",
                "subJotunnPortalOfIce14|Portal Major",
            ]
        )
        save = SAMPLE_SAVE.replace('class="1.000000"', 'class="18.000000"')
        save += (
            "\n[talent_loadout_0]\n"
            'talent_327="1.000000"\n'
            'talent_332="1.000000"\n'
            'subtalents="e30="\n'
        )
        with tempfile.TemporaryDirectory() as directory:
            talent_path = Path(directory) / "translationsTalent.csv"
            subtalent_path = Path(directory) / "translationsSubTalent.csv"
            talent_path.write_text(talent_text, encoding="utf-8")
            subtalent_path.write_text(subtalent_text, encoding="utf-8")
            pair = (talent_path, subtalent_path)
            resolved_ids = editor.resolve_allocated_subtalent_ids(save, 0, pair)
            definitions = editor.resolve_allocated_subtalent_definitions(save, 0, pair)

        self.assertEqual(resolved_ids, {327, 332})
        self.assertEqual(
            [(definition.talent_id, definition.skill_name) for definition in definitions],
            [(327, "breathOfIce"), (332, "portalOfIce")],
        )

    def test_necromancer_native_ids_match_game_written_subskill_trees(self):
        necromancer_keys = editor.S10_CLASS_TALENT_KEYS[7]
        talent_text = "\n".join(f"talent_name_{key}|{key}" for key in necromancer_keys)
        subtalent_text = "\n".join(
            [
                "subNecromancerPoisonNova01|Poison Node",
                "subNecromancerCorpseExplosion01|Corpse Node",
                "subNecromancerRaiseSkeleton01|Warrior Node",
                "subNecromancerRaiseSkeletonMage01|Mage Node",
            ]
        )

        definitions = editor.subtalent_tree_definitions_from_translations(
            "Necromancer",
            7,
            talent_text,
            subtalent_text,
        )

        self.assertEqual(
            [(definition.talent_id, definition.skill_name) for definition in definitions],
            [
                (117, "corpseExplosion"),
                (118, "poisonNova"),
                (120, "raiseSkeletonWarrior"),
                (122, "raiseSkeletonMage"),
            ],
        )
        self.assertEqual(definitions[2].small_node_caps[0], 3)

    def test_necromancer_legacy_passive_tree_ids_migrate_to_native_ids(self):
        legacy = {
            "t120": {"s1": 3.0, "s11": 3.0},
            "t121": {"s1": 5.0, "s12": 3.0},
        }
        save = SAMPLE_SAVE.replace('class="1.000000"', 'class="7.000000"')
        save = editor.set_ini_value(save, "0", "talent_loadout", "0", "number")
        save = editor.set_ini_value(
            save,
            "talent_loadout_0",
            "subtalents",
            editor.encode_base64_json(legacy),
            "text",
        )

        migrated, tree_count = editor.migrate_legacy_subtalent_tree_ids(save, 0)
        trees = editor.decode_subtalent_map(migrated, 0)

        self.assertEqual(tree_count, 1)
        self.assertEqual(trees, {"t120": legacy["t120"], "t122": legacy["t121"]})

    def test_necromancer_migration_never_discards_a_populated_native_conflict(self):
        trees = {
            "t121": {"s1": 5.0},
            "t122": {"s1": 1.0},
        }
        save = SAMPLE_SAVE.replace('class="1.000000"', 'class="7.000000"')
        save = editor.set_ini_value(
            save,
            "talent_loadout_0",
            "subtalents",
            editor.encode_base64_json(trees),
            "text",
        )

        migrated, tree_count = editor.migrate_legacy_subtalent_tree_ids(save, 0)

        self.assertEqual(tree_count, 0)
        self.assertEqual(editor.decode_subtalent_map(migrated, 0), trees)

    def test_cross_release_ambiguous_tree_ids_are_never_auto_migrated(self):
        cases = (
            (8, {"t138": {"s1": 4.0}}),
            (9, {"t151": {"s1": 2.0}, "t159": {"s1": 5.0}}),
            (18, {"t311": {"s1": 2.0}, "t316": {"s1": 3.0}, "t318": {"s1": 4.0}}),
        )
        for class_id, trees in cases:
            with self.subTest(class_id=class_id):
                save = SAMPLE_SAVE.replace('class="1.000000"', f'class="{class_id}.000000"')
                save = editor.set_ini_value(
                    save,
                    "talent_loadout_0",
                    "subtalents",
                    editor.encode_base64_json(trees),
                    "text",
                )

                migrated, tree_count = editor.migrate_legacy_subtalent_tree_ids(save, 0)

                self.assertEqual(tree_count, 0)
                self.assertEqual(editor.decode_subtalent_map(migrated, 0), trees)

    def test_legacy_poison_nova_t119_migrates_to_native_t118(self):
        trees = {"t119": {"s1": 5.0, "s13": 3.0}}
        save = sample_save_for_class(7)
        save = editor.set_ini_value(
            save,
            "talent_loadout_0",
            "subtalents",
            editor.encode_base64_json(trees),
            "text",
        )

        migrated, tree_count = editor.migrate_legacy_subtalent_tree_ids(save, 0)

        self.assertEqual(tree_count, 1)
        self.assertEqual(editor.decode_subtalent_map(migrated, 0), {"t118": trees["t119"]})

    def test_converging_legacy_sources_are_preserved_instead_of_guessed(self):
        trees = {"t8": {"s1": 5.0, "s11": 3.0}, "t9": {"s1": 2.0, "s12": 3.0}}
        save = sample_save_for_class(1)
        save = editor.set_ini_value(
            save,
            "talent_loadout_0",
            "subtalents",
            editor.encode_base64_json(trees),
            "text",
        )

        migrated, tree_count = editor.migrate_legacy_subtalent_tree_ids(save, 0)

        self.assertEqual(tree_count, 0)
        self.assertEqual(editor.decode_subtalent_map(migrated, 0), trees)

    def test_every_legacy_invalid_tree_migrates_only_to_a_verified_native_tree(self):
        payload = "\n".join(
            f"{class_id}:{old_id}>{native_id}"
            for class_id in sorted(editor.S10_LEGACY_SUBTALENT_TREE_ID_MIGRATIONS)
            for old_id, native_id in sorted(
                editor.S10_LEGACY_SUBTALENT_TREE_ID_MIGRATIONS[class_id].items()
            )
        )
        self.assertEqual(payload.count("\n") + 1, 81)
        self.assertEqual(
            hashlib.sha256(payload.encode("utf-8")).hexdigest(),
            "be7fdd502c7e1d1c5d1195e5c108edea1c370e8bc2f98bb4dc9c75ea73f10b0f",
        )
        for class_id, migrations in editor.S10_LEGACY_SUBTALENT_TREE_ID_MIGRATIONS.items():
            class_active_ids = editor.verified_class_subtalent_ids(class_id)
            for old_id, native_id in migrations.items():
                original = {f"t{old_id}": {"s1": 4.0, "s13": 3.0}}
                save = sample_save_for_class(class_id)
                save = editor.set_ini_value(
                    save,
                    "talent_loadout_0",
                    "subtalents",
                    editor.encode_base64_json(original),
                    "text",
                )

                migrated, tree_count = editor.migrate_legacy_subtalent_tree_ids(save, 0)

                with self.subTest(class_id=class_id, old_id=old_id, native_id=native_id):
                    self.assertEqual(tree_count, 1)
                    self.assertEqual(
                        editor.decode_subtalent_map(migrated, 0),
                        {f"t{native_id}": original[f"t{old_id}"]},
                    )
                    self.assertNotIn(old_id, class_active_ids)
                    self.assertIn(native_id, class_active_ids)
                    migrated_again, second_count = editor.migrate_legacy_subtalent_tree_ids(
                        migrated, 0
                    )
                    self.assertEqual(second_count, 0)
                    self.assertEqual(migrated_again, migrated)

    def test_native_jotunn_and_illusionist_tree_ids_are_never_migrated(self):
        for class_id, native_id in ((18, 326), (19, 308)):
            trees = {f"t{native_id}": {"s1": 5.0, "s11": 3.0}}
            save = sample_save_for_class(class_id)
            save = editor.set_ini_value(
                save,
                "talent_loadout_0",
                "subtalents",
                editor.encode_base64_json(trees),
                "text",
            )

            migrated, tree_count = editor.migrate_legacy_subtalent_tree_ids(save, 0)

            with self.subTest(class_id=class_id, native_id=native_id):
                self.assertEqual(tree_count, 0)
                self.assertEqual(editor.decode_subtalent_map(migrated, 0), trees)

    def test_historical_subtalent_parent_names_map_to_current_skill_keys(self):
        aliases = {
            ("Viking", "Throw"): "monsterthrow",
            ("Pirate", "FreezingChainShot"): "freezechainshot",
            ("Redneck", "ChainSlash"): "chainsawslash",
            ("Necromancer", "RaiseSkeleton"): "raiseskeletonwarrior",
            ("Necromancer", "VengefulSpirit"): "summonvengefulspirit",
            ("Jotunn", "SweepFreeze"): "frostsunder",
            ("Prophet", "SpiritOfVendigo"): "spiritofwendigo",
            ("Prophet", "StormHawk"): "spiritofhawk",
        }
        for (class_prefix, parent_key), expected in aliases.items():
            with self.subTest(class_prefix=class_prefix, parent_key=parent_key):
                self.assertEqual(
                    editor.canonical_subtalent_parent(class_prefix, parent_key),
                    expected,
                )

    def test_resolver_creates_ids_only_for_allocated_active_shaman_talents(self):
        keys = editor.S10_CLASS_TALENT_KEYS[13]
        talent_text = "\n".join(f"talent_name_{key}|{key}" for key in keys)
        subtalent_text = "\n".join(
            [
                "subShamanTectonicBoulder01|A",
                "subShamanTornado01|B",
                "subShamanChaosTotem01|C",
            ]
        )
        save = SAMPLE_SAVE.replace('class="1.000000"', 'class="13.000000"')
        save += (
            "\n[talent_loadout_0]\n"
            'talent_218="1.000000"\n'
            'talent_219="20.000000"\n'
            'talent_222="1.000000"\n'
            'talent_235="1.000000"\n'
            'subtalents="e30="\n'
        )
        with tempfile.TemporaryDirectory() as directory:
            talent_path = Path(directory) / "translationsTalent.csv"
            subtalent_path = Path(directory) / "translationsSubTalent.csv"
            talent_path.write_text(talent_text, encoding="utf-8")
            subtalent_path.write_text(subtalent_text, encoding="utf-8")
            resolved = editor.resolve_allocated_subtalent_ids(
                save,
                0,
                (talent_path, subtalent_path),
            )
        self.assertEqual(resolved, {218, 222, 235})

    def test_active_talent_loadout_rejects_invalid_values(self):
        save = editor.set_ini_value(SAMPLE_SAVE, "0", "talent_loadout", "8", "number")
        with self.assertRaises(ValueError):
            editor.active_talent_loadout_index(save)


if __name__ == "__main__":
    unittest.main()
