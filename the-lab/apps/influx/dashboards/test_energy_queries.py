#!/usr/bin/env python3
"""Contract for the Waid / Energy dashboard.

Today and History read energy_balance / energy_hourly. They do not
integrate watts. Year comparison stays on the integral archive.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
DASHBOARD = HERE / "energy.json"
YEAR = HERE / "year-comparison.json"
LEGACY_TASK = HERE.parent / "tasks" / "downsample-energy-daily.flux"

TODAY_TITLES = {
    "Produced",
    "Kept",
    "Exported",
    "From grid",
    "Unaccounted",
    "Autarky",
    "Self-consumption",
}

REQUIRED_TITLES = TODAY_TITLES | {
    "Right now",
    "House",
    "When the balcony exports",
}

GONE_BATTERY_TITLES = {
    "Shifted",
    "Saved",
    "Payback",
    "Max price",
    "Left on the grid",
}

GONE_BATTERY_VARS = {
    "battery_kwh",
    "battery_chf",
    "battery_eta",
    "payback_years",
}

RATE_VARS = {
    "buy_ht": "0.2625",
    "buy_nt": "0.1590",
    "feed_ht": "0.1050",
    "feed_nt": "0.0645",
}


def walk_panels(panels: list) -> list[dict]:
    out: list[dict] = []
    for panel in panels:
        out.append(panel)
        out.extend(walk_panels(panel.get("panels") or []))
    return out


def panel_queries(dashboard: dict) -> list[tuple[int, str, str]]:
    out = []
    for panel in walk_panels(dashboard.get("panels", [])):
        title = panel.get("title", "")
        for target in panel.get("targets", []):
            query = target.get("query")
            if query:
                out.append((panel.get("id", 0), title, query))
    return out


class EnergyQueryContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dashboard = json.loads(DASHBOARD.read_text())
        cls.queries = panel_queries(cls.dashboard)
        cls.titles = {title for _pid, title, _q in cls.queries}
        cls.row_titles = {
            p.get("title")
            for p in walk_panels(cls.dashboard.get("panels", []))
            if p.get("type") == "row"
        }
        cls.vars = {
            v["name"]: v for v in cls.dashboard.get("templating", {}).get("list", [])
        }

    def test_required_panel_titles_exist(self) -> None:
        missing = REQUIRED_TITLES - {
            p.get("title") for p in walk_panels(self.dashboard.get("panels", []))
        }
        self.assertEqual(missing, set())

    def test_today_stats_do_not_integrate_watts(self) -> None:
        today = [
            (pid, title, query)
            for pid, title, query in self.queries
            if title in TODAY_TITLES or (title == "House" and "energy_balance" in query)
        ]
        self.assertTrue(today, "Today panels are missing")
        bad = []
        for pid, title, query in today:
            if "integral(" in query:
                bad.append(f"{pid} {title}: integral")
            if "energy_balance" not in query:
                bad.append(f"{pid} {title}: no energy_balance")
        self.assertEqual(bad, [])

    def test_money_is_the_only_rate_consumer(self) -> None:
        rate_tokens = tuple(RATE_VARS)
        money_hits = []
        identity_hits = []
        for pid, title, query in self.queries:
            uses = [t for t in rate_tokens if f"${{{t}}}" in query or f"${t}" in query]
            if not uses:
                continue
            if title in TODAY_TITLES or (
                title == "House" and "energy_balance" in query
            ):
                identity_hits.append(f"{pid} {title}: {uses}")
            else:
                money_hits.append((pid, title, uses))
        self.assertTrue(
            money_hits, "Paid / Credited / Kept worth must use the rate variables"
        )
        self.assertEqual(identity_hits, [])
        used = {name for _pid, _title, names in money_hits for name in names}
        self.assertEqual(used, set(RATE_VARS))

    def test_rate_variables_hidden_with_defaults(self) -> None:
        self.assertNotIn("tariff", self.vars)
        for name, default in RATE_VARS.items():
            var = self.vars.get(name)
            self.assertIsNotNone(var, name)
            self.assertEqual(var.get("hide"), 2, name)
            self.assertEqual(var.get("type"), "textbox", name)
            current = var.get("current") or {}
            self.assertIn(default, (current.get("value"), var.get("query")), name)

    def test_history_excludes_open_day_and_uses_day_start(self) -> None:
        history = [
            (pid, title, query)
            for pid, title, query in self.queries
            if title in {"When the balcony exports"}
            or "energy_balance" in query
            and title not in TODAY_TITLES
            and "House" != title
            or (
                title in {"Export", "From grid"}
                and "energy_hourly" not in query
                and "1d" in query
            )
        ]
        bar_queries = [
            query
            for _pid, title, query in self.queries
            if "energy_balance" in query
            and title not in TODAY_TITLES | {"House", "Autarky", "Self-consumption"}
        ]
        # House composition and export history must stop at today's midnight.
        closed = [
            query
            for _pid, title, query in self.queries
            if "energy_balance" in query
            and "date.truncate" in query
            and title not in TODAY_TITLES
            and not title.startswith("Autarky")
            and title != "Self-consumption"
            and title != "House"
        ]
        self.assertTrue(
            any(
                "energy_balance" in q and "date.truncate" in q
                for q in [q for _, _, q in self.queries]
            ),
            "history must filter energy_balance and truncate the open day",
        )
        for query in closed:
            self.assertNotIn("timeShift", query)
            self.assertIn("date.truncate", query)

    def test_hour_of_day_is_mean_export(self) -> None:
        hits = [
            query
            for _pid, title, query in self.queries
            if title == "When the balcony exports"
        ]
        self.assertTrue(hits)
        for query in hits:
            self.assertIn("energy_hourly", query)
            self.assertIn("export_kwh", query)

    def test_hour_of_day_uses_clock_hour_labels(self) -> None:
        panels = [
            p
            for p in walk_panels(self.dashboard.get("panels", []))
            if p.get("title") == "When the balcony exports"
        ]
        self.assertTrue(panels)
        for panel in panels:
            query = "".join(t.get("query") or "" for t in panel.get("targets", []))
            self.assertNotIn("1970-01-01", query)
            self.assertNotIn('_field: "Export"', query)
            after = query.split("mean()", 1)[1]
            self.assertIn("Hour:", after)
            self.assertIn('":00"', after)
            self.assertRegex(after, r"group\(\s*\)")
            self.assertEqual(panel.get("options", {}).get("xField"), "Hour")

    def test_legacy_yoy_untouched(self) -> None:
        year = json.loads(YEAR.read_text())
        text = json.dumps(year)
        self.assertIn("grid_net_kwh", text)
        self.assertNotIn("energy_balance", text)

    def test_integral_archive_still_written(self) -> None:
        flux = LEGACY_TASK.read_text()
        self.assertIn("integral(unit: 1h)", flux)
        self.assertIn("grid_import_kwh", flux)

    def test_energy_balance_task_has_no_battery(self) -> None:
        flux = (HERE.parent / "tasks" / "energy-balance.flux").read_text()
        self.assertNotIn("battery", flux.lower())

    def test_flux_if_after_plus_is_parenthesized(self) -> None:
        bad = []
        for pid, title, query in self.queries:
            if re.search(r"\+ if ", query):
                bad.append(f"{pid} {title}")
        self.assertEqual(bad, [])

    def test_now_house_watts_sums_without_pivot(self) -> None:
        houses = [
            (pid, title, query)
            for pid, title, query in self.queries
            if title == "House" and "total_act_power" in query
        ]
        self.assertTrue(houses)
        for pid, title, query in houses:
            self.assertIn("|> sum()", query)
            self.assertNotIn('pivot(rowKey: ["_time"]', query)
            self.assertIn("toFloat()", query)

    def test_ratio_panels_keep_today_and_median_names(self) -> None:
        for title in ("Autarky", "Self-consumption"):
            hits = [query for _pid, t, query in self.queries if t == title]
            self.assertTrue(hits, title)
            for query in hits:
                self.assertIn("30d median", query)
                self.assertIn('group(columns: ["_field"])', query)

    def test_power_chart_joins_grid_and_solar(self) -> None:
        hits = [
            query
            for _pid, title, query in self.queries
            if title == "Load / Solar / Grid"
        ]
        self.assertTrue(hits)
        for query in hits:
            union_at = query.index("union(tables: [grid, solar])")
            after = query[union_at:]
            self.assertIn("|> group()", after)
            self.assertIn("exists r.grid", after)
            self.assertLess(after.index("|> group()"), after.index("pivot("))

    def test_power_chart_floors_window_and_leaves_missing_grid(self) -> None:
        hits = [
            query
            for _pid, title, query in self.queries
            if title == "Load / Solar / Grid"
        ]
        self.assertTrue(hits)
        for query in hits:
            self.assertIn("30s", query)
            self.assertIn("v.windowPeriod", query)
            self.assertRegex(
                query,
                r"every\s*=\s*if\s+uint\(v:\s*v\.windowPeriod\)\s*<\s*uint\(v:\s*30s\)\s+then\s+30s\s+else\s+v\.windowPeriod",
            )
            self.assertIn("aggregateWindow(every: every,", query)
            self.assertNotIn("else 0.0", query.split("g = ", 1)[1].split("s = ", 1)[0])
            self.assertIn(
                "else math.NaN()", query.split("g = ", 1)[1].split("s = ", 1)[0]
            )
            house = query.split('"House load":', 1)[1]
            self.assertIn("exists r.grid", house)
            self.assertNotRegex(house, r"g \+ s\s*}")

    def test_power_chart_paints_import_export_area(self) -> None:
        panels = [
            p
            for p in walk_panels(self.dashboard.get("panels", []))
            if p.get("title") == "Load / Solar / Grid"
        ]
        self.assertTrue(panels)
        for panel in panels:
            defaults = panel["fieldConfig"]["defaults"]
            self.assertEqual(defaults["custom"]["thresholdsStyle"]["mode"], "area")
            steps = defaults["thresholds"]["steps"]
            self.assertEqual(steps[0]["color"], "green")
            self.assertEqual(steps[1]["value"], 0)
            self.assertEqual(steps[1]["color"], "red")
            sun_off = False
            for override in panel["fieldConfig"]["overrides"]:
                name = override.get("matcher", {}).get("options")
                if name not in {"Sun altitude", "B"}:
                    continue
                for prop in override.get("properties", []):
                    if prop.get("id") == "custom.thresholdsStyle":
                        sun_off = prop.get("value", {}).get("mode") == "off"
            self.assertTrue(sun_off, "Sun altitude must not paint the watt bands")

    def test_power_chart_hides_idle_solar(self) -> None:
        hits = [
            query
            for _pid, title, query in self.queries
            if title == "Load / Solar / Grid"
        ]
        self.assertTrue(hits)
        for query in hits:
            solar = query.split("solar = ", 1)[1].split("union(", 1)[0]
            self.assertIn("filter(fn: (r) => r._value > 0.0)", solar)
            self.assertIn('import "math"', query)
            self.assertIn("math.NaN()", query)
            self.assertRegex(
                query,
                r"Solar: if .+ then .+ else math\.NaN\(\)",
            )

    def test_inverter_status_casts_before_union(self) -> None:
        hits = [query for _pid, title, query in self.queries if title == "Inverter"]
        self.assertTrue(hits)
        for query in hits:
            self.assertIn("toFloat()", query)
            self.assertIn("union(tables: [solar, reach])", query)
            self.assertIn('group(columns: ["_field"])', query)

    def test_dashboard_has_no_battery_counterfactual(self) -> None:
        titles = {p.get("title") for p in walk_panels(self.dashboard.get("panels", []))}
        leftover = (GONE_BATTERY_TITLES | {"Battery"}) & titles
        leftover |= {
            title
            for title in titles
            if isinstance(title, str) and title.startswith("Battery")
        }
        self.assertEqual(leftover, set())
        self.assertEqual(GONE_BATTERY_VARS & set(self.vars), set())
        for _pid, title, query in self.queries:
            self.assertNotIn("battery_", query, title)
            self.assertNotIn("payback_years", query, title)


if __name__ == "__main__":
    unittest.main()
