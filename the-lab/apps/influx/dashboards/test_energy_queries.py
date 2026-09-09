#!/usr/bin/env python3
"""Static checks for Waid Energy Flux queries.

These would have caught the 2026-09-09 No-data KPIs:
- Flux rejects `x + if ...` without parentheses
- integral() after bare group() drops _start/_stop from the group key
- Grafana stat panels ignore integral rows that have no _time
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

DASHBOARD = Path(__file__).with_name("energy.json")

# Panels that integrate watts over "today" (must keep range bounds grouped).
INTEGRAL_PANELS = {4, 5, 6, 21, 22, 23, 24}


def panel_queries(dashboard: dict) -> list[tuple[int, str, str]]:
    out = []
    for panel in dashboard["panels"]:
        title = panel.get("title", "")
        for target in panel.get("targets", []):
            query = target.get("query")
            if query:
                out.append((panel["id"], title, query))
    return out


class EnergyQueryContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dashboard = json.loads(DASHBOARD.read_text())
        cls.queries = panel_queries(cls.dashboard)

    def test_flux_if_after_plus_is_parenthesized(self) -> None:
        bad = []
        for pid, title, query in self.queries:
            if re.search(r"\+ if ", query):
                bad.append(f"{pid} {title}")
        self.assertEqual(
            bad,
            [],
            "Flux parses `+ if` as invalid; wrap: x + (if ... then ... else ...)",
        )

    def test_integral_keeps_start_stop_in_group_key(self) -> None:
        missing = []
        for pid, title, query in self.queries:
            if pid not in INTEGRAL_PANELS:
                continue
            if "integral(unit: 1h)" not in query:
                missing.append(f"{pid} {title}: no integral")
                continue
            if 'group(columns: ["_start", "_stop"])' not in query:
                missing.append(f"{pid} {title}: integral without grouped _start/_stop")
        self.assertEqual(missing, [])

    def test_integral_results_set_time(self) -> None:
        missing = []
        for pid, title, query in self.queries:
            if pid not in INTEGRAL_PANELS:
                continue
            if "_time: r._stop" not in query:
                missing.append(f"{pid} {title}: integral map missing _time: r._stop")
        self.assertEqual(missing, [])

    def test_house_load_does_not_pivot_on_mismatched_last_timestamps(self) -> None:
        house = next(q for pid, title, q in self.queries if pid == 1)
        self.assertIn("|> sum()", house)
        self.assertNotIn("pivot(rowKey: [\"_time\"]", house)


if __name__ == "__main__":
    unittest.main()
