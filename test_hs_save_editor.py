import unittest
from pathlib import Path

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


class Season10ProgressTests(unittest.TestCase):
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

    def test_waypoints_cover_full_s10_schema(self):
        result = editor.unlock_all_waypoints(SAMPLE_SAVE)
        for act in range(1, 10):
            self.assertEqual(editor.get_ini_value(result, "0", f"act_{act}"), "4.000000")
            for zone in range(10):
                self.assertEqual(editor.get_ini_value(result, "0", f"zone{act},{zone}"), "4.000000")

    def test_difficulty_unlock_preserves_current_selection_and_legacy_value(self):
        result = editor.unlock_all_difficulties(SAMPLE_SAVE)
        self.assertEqual(editor.get_ini_value(result, "0", "difficulty"), "1.000000")
        self.assertEqual(editor.get_ini_value(result, "0", "hell_subdifficulty"), "5.000000")
        self.assertEqual(editor.get_ini_value(result, "0", "act_9"), "4.000000")

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
        data = editor.set_ether_loadout_nodes(editor.default_ether_data(), 2, [46, 46, 0, 215])
        self.assertEqual(editor.ether_loadout_nodes(data, 2), [46, 46, 0, 215])
        self.assertEqual(editor.parse_ether_node_ids("46, 46; 0 215"), [46, 46, 0, 215])

    def test_s10_ether_sidecar_matches_character_slot(self):
        path = Path(r"C:\save\herosiege19.hss")
        self.assertEqual(editor.ether_path_for_character(path), Path(r"C:\save\ether19.hss"))


if __name__ == "__main__":
    unittest.main()
