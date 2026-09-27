import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.static_site import collect_detail_paths


class StaticDetailPathTests(unittest.TestCase):
    def test_routes_use_the_static_build_data_directory(self):
        fixture = {
            "ei_maps": [{"name": "D130"}],
            "monsters": [{"name": "Pig"}],
            "items": [{"id": 685}],
            "skills": [{"id": 2}],
            "npcs": [{"id": 7}],
            "quests": [{"name": "First Quest"}],
        }
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, "wiki_data_v2.json").write_text(json.dumps(fixture), encoding="utf-8")
            Path(temp, "wiki_all.json").write_text(
                json.dumps({"SetInfo": {"rows": [{"SetName": "Set Alpha"}]}}), encoding="utf-8"
            )
            Path(temp, "wiki_stores.json").write_text(json.dumps({"stores": [{}, {}]}), encoding="utf-8")
            with patch.dict(os.environ, {"MIR2EI_DATA": temp}):
                paths = collect_detail_paths("http://127.0.0.1:8777", 8777)

        self.assertEqual(
            paths,
            {
                "/map/D130",
                "/monster/Pig",
                "/item/685",
                "/skill/2",
                "/npc/7",
                "/quest/First%20Quest",
                "/set/Set%20Alpha",
                "/store/0",
                "/store/1",
            },
        )


if __name__ == "__main__":
    unittest.main()
