import copy
import json
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit

from scripts.build_zircon_name_audit import build_audit, build_link_index


FIXTURE = Path(__file__).parent / "fixtures" / "zircon_name_audit.json"
CATEGORIES = ("items", "monsters", "npcs", "magics", "maps")


class ZirconNameAuditTests(unittest.TestCase):
    def setUp(self):
        self.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.site = tempfile.TemporaryDirectory()
        self.site_root = Path(self.site.name)
        for relative in (
            "item/685.html", "item/1092.html", "item/1093.html", "item/777.html",
            "item/999.html", "item/1001.html", "item/1002.html",
            "monster/Pig.html", "monster/Pachon.html", "monster/SummonPuppet.html", "monster/Unlisted Beast.html",
            "npc/47.html", "skill/1.html", "skill/2.html",
            "map/0.map.html", "map/01_003.map.html", "map/02_001.map.html",
            "img/items/685.png", "img/items/1092.png", "img/items/1093.png",
            "img/items/999.png", "img/items/1001.png", "img/items/1002.png",
            "img/monsters/9.png", "img/monsters/189.png", "img/npcs_face/47.png",
            "img/npcs/47.png", "img/skills/1.png", "img/skills/2.png",
            "thumb/0.map.png", "thumb/01_003.map.png", "thumb/02_001.map.png",
        ):
            path = self.site_root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"fixture resource")

    def tearDown(self):
        self.site.cleanup()

    def build(self):
        return build_audit(
            self.fixture["names"], self.fixture["wiki_all"], self.fixture["wiki_data_v2"],
            self.site_root, self.fixture["provenance"],
        )

    @staticmethod
    def system_record(audit, category, index):
        return next(
            record for record in audit["records"]
            if record["category"] == category
            and record["source"] is not None
            and record["source"]["index"] == index
        )

    def test_stable_id_and_name_agreement_is_a_candidate_not_verified_correct(self):
        record = self.system_record(self.build(), "items", 685)

        self.assertEqual(record["identity"]["status"], "matched")
        self.assertEqual(record["identity"]["method"], "stable_id_and_exact_name")
        self.assertEqual(record["translation_assessment"], "agrees_with_encyclopedia")
        self.assertEqual(record["translation"]["zh_raw"], "来世")
        self.assertEqual(record["translation"]["ja_raw"], "来世")
        self.assertEqual(record["review_status"], "not_reviewed")
        self.assertFalse(record["translation"].get("verified_correct", False))

    def test_translation_disagreement_is_suspected_not_asserted_wrong(self):
        record = self.system_record(self.build(), "magics", 2)

        self.assertEqual(record["identity"]["status"], "matched")
        self.assertEqual(record["translation_assessment"], "suspected_mismatch")
        self.assertIn("differs_from_encyclopedia", record["translation_flags"])
        self.assertEqual(record["status"], "suspected_mismatch")
        self.assertEqual(record["translation"]["zh_raw"], "药剂精通")
        self.assertEqual(record["wiki"]["zh"], "药水精通")

    def test_translation_flags_overlap_without_hiding_site_disagreement(self):
        audit = self.build()
        record = self.system_record(audit, "items", 1002)

        self.assertEqual(record["translation_assessment"], "suspected_mismatch")
        self.assertEqual(record["wiki"]["zh"], "测试标记")
        self.assertTrue({
            "differs_from_encyclopedia", "suspected_untranslated",
        }.issubset(record["translation_flags"]))
        self.assertEqual(audit["summary"]["items"]["suspected_mismatches"], 1)
        self.assertEqual(audit["summary"]["items"]["suspected_untranslated"], 1)

    def test_duplicate_translation_key_keeps_each_item_and_sprite_conflict(self):
        audit = self.build()
        first = self.system_record(audit, "items", 1092)
        second = self.system_record(audit, "items", 1093)

        self.assertNotEqual(first["record_id"], second["record_id"])
        self.assertEqual(first["translation"]["english_key_entity_count"], 2)
        self.assertIn("mapping_key_fanout", first["issues"])
        self.assertIn("sprite_attribute_conflict", first["issues"])
        self.assertEqual(first["identity"]["status"], "conflict")
        self.assertEqual(second["status"], "conflict")
        self.assertEqual(first["wiki"]["page_url"], "/item/1092.html")
        self.assertEqual(second["wiki"]["page_url"], "/item/1093.html")

    def test_same_monster_name_with_distinct_indices_is_not_collapsed(self):
        audit = self.build()
        pig_rows = [
            record for record in audit["records"]
            if record["category"] == "monsters"
            and record["source"] is not None
            and record["source"]["english_key"] == "Pig"
        ]

        self.assertEqual({record["source"]["index"] for record in pig_rows}, {9, 189})
        self.assertTrue(all(record["status"] == "conflict" for record in pig_rows))
        self.assertTrue(all(record["wiki"]["page_url"] is None for record in pig_rows))
        self.assertTrue(all(record["wiki"]["candidate_page_urls"] == ["/monster/Pig.html"] for record in pig_rows))

    def test_normalized_name_is_candidate_recall_only(self):
        record = self.system_record(self.build(), "monsters", 196)

        self.assertEqual(record["source"]["english_key"], "Pachon ")
        self.assertIsNone(record["translation"]["zh_raw"])
        self.assertEqual(record["translation_assessment"], "missing")
        self.assertEqual(record["identity"]["status"], "needs_evidence")
        self.assertEqual(record["candidate_mapping_keys"][0]["english_key"], "Pachon")
        self.assertNotEqual(record["wiki"]["name"], record["source"]["english_key"])

    def test_missing_zh_and_missing_image_are_separate_evidence_gaps(self):
        audit = self.build()
        item = self.system_record(audit, "items", 777)
        monster = self.system_record(audit, "monsters", 140)

        self.assertEqual(item["translation_assessment"], "missing")
        self.assertEqual(item["status"], "missing_translation")
        self.assertEqual(item["wiki"]["image_url"], "/img/items/777.png")
        self.assertFalse(item["wiki"]["image_exists"])
        self.assertEqual(monster["translation_assessment"], "agrees_with_encyclopedia")
        self.assertEqual(monster["wiki"]["image_url"], "/img/monsters/140.png")
        self.assertFalse(monster["wiki"]["image_exists"])
        self.assertEqual(monster["visual_evidence"]["status"], "image_unavailable")
        self.assertEqual(monster["review_status"], "not_reviewed")

    def test_duplicate_map_names_keep_separate_file_identity_and_conflict(self):
        audit = self.build()
        trial_maps = [
            record for record in audit["records"]
            if record["category"] == "maps"
            and record["source"] is not None
            and record["source"]["english_key"] == "试练场"
        ]

        self.assertEqual({record["source"]["index"] for record in trial_maps}, {615, 617})
        self.assertEqual({record["wiki"]["page_url"] for record in trial_maps}, {
            "/map/01_003.map.html", "/map/02_001.map.html",
        })
        self.assertTrue(all(record["status"] == "conflict" for record in trial_maps))

    def test_map_link_translation_evidence_names_its_source_file(self):
        fixture = copy.deepcopy(self.fixture)
        fixture["wiki_data_v2"]["_map_link_names"] = {"01_003": "试练场"}
        audit = build_audit(
            fixture["names"], fixture["wiki_all"], fixture["wiki_data_v2"],
            self.site_root, fixture["provenance"],
        )
        record = self.system_record(audit, "maps", 615)

        self.assertEqual(record["wiki"]["translation_source"], "data/map_links.json")
        self.assertIn("data/map_links.json", {evidence["source"] for evidence in record["evidence"]})
        self.assertIn("agrees_with_encyclopedia", record["translation_flags"])

    def test_unmatched_site_entity_is_not_labeled_zircon_only(self):
        audit = self.build()
        site_record = next(
            record for record in audit["records"]
            if record["category"] == "items" and record["kind"] == "wiki_entity"
            and record["wiki"]["entity_id"] == 1001
        )

        self.assertEqual(site_record["status"], "wiki_unlinked")
        self.assertEqual(site_record["identity"]["status"], "unmatched")
        self.assertNotIn("zircon_only", site_record["issues"])

        map_record = next(
            record for record in audit["records"]
            if record["category"] == "maps" and record["kind"] == "wiki_supplemental"
        )
        self.assertEqual(map_record["wiki"]["name"], "Unlinked Map Data")
        self.assertEqual(map_record["wiki"]["page_url_candidate"], "/map/orphan.map.html")
        self.assertEqual(audit["summary"]["maps"]["unlinked_supplemental_website_records"], 1)
        self.assertEqual(
            next(entry for entry in build_link_index(audit) if entry["record_id"] == map_record["record_id"])
            ["page_relation"],
            "candidate",
        )

    def test_output_is_deterministic_unique_and_does_not_mutate_inputs(self):
        before = copy.deepcopy((self.fixture["names"], self.fixture["wiki_all"], self.fixture["wiki_data_v2"]))
        first = self.build()
        second = self.build()

        self.assertEqual(first, second)
        self.assertEqual((self.fixture["names"], self.fixture["wiki_all"], self.fixture["wiki_data_v2"]), before)
        record_ids = [record["record_id"] for record in first["records"]]
        self.assertEqual(len(record_ids), len(set(record_ids)))
        self.assertEqual(set(first["summary"]), set(CATEGORIES))
        self.assertIn("wiki_all_sha256", first["provenance"]["wiki"])
        self.assertNotIn("/home/", json.dumps(first, ensure_ascii=False))

    def test_published_resource_references_match_files_and_link_index_keeps_records(self):
        audit = self.build()
        for record in audit["records"]:
            wiki = record["wiki"]
            if wiki["page_url"]:
                path = self.site_root / unquote(urlsplit(wiki["page_url"]).path.lstrip("/"))
                self.assertTrue(path.is_file(), wiki["page_url"])
            if wiki["image_url"]:
                path = self.site_root / unquote(urlsplit(wiki["image_url"]).path.lstrip("/"))
                self.assertEqual(wiki["image_exists"], path.is_file(), wiki["image_url"])

        index = build_link_index(audit)
        pig_links = [entry for entry in index if entry["page_url"] == "/monster/Pig.html"]
        self.assertEqual(len(pig_links), 2)
        self.assertGreaterEqual(audit["summary"]["items"]["sprite_conflicts"], 1)


if __name__ == "__main__":
    unittest.main()
