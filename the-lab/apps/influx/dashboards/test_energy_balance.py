#!/usr/bin/env python3
"""Oracle and contract for the Energy balance Flux task."""

from __future__ import annotations

import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
TASK = HERE.parent / "tasks" / "energy-balance.flux"
SETUP = HERE.parent / "tasks" / "sync-archive.sh"

ZURICH = ZoneInfo("Europe/Zurich")
HOCH_PREDICATE = (
    "date.weekDay(t: t) != 0 and date.hour(t: t) >= 6 and date.hour(t: t) < 22"
)


def is_hochtarif(t: datetime) -> bool:
    """Europe/Zurich Hoch tarif: Monday–Saturday, hour in [6, 22). Sunday is 0."""
    local = t.astimezone(ZURICH)
    return local.weekday() != 6 and local.hour >= 6 and local.hour < 22


def day_balance(
    *,
    solar_kwh: float,
    solar_ht_kwh: float,
    solar_nt_kwh: float,
    import_kwh: float,
    import_ht_kwh: float,
    import_nt_kwh: float,
    export_kwh: float,
    export_ht_kwh: float,
    export_nt_kwh: float,
) -> dict[str, float]:
    kept_ht_kwh = solar_ht_kwh - export_ht_kwh
    if kept_ht_kwh < 0.0:
        kept_ht_kwh = 0.0
    kept_nt_kwh = solar_nt_kwh - export_nt_kwh
    if kept_nt_kwh < 0.0:
        kept_nt_kwh = 0.0
    residual_kwh = (
        solar_kwh
        - kept_ht_kwh
        - kept_nt_kwh
        - export_kwh
        + (import_kwh - import_ht_kwh - import_nt_kwh)
        + (export_kwh - export_ht_kwh - export_nt_kwh)
    )
    return {
        "kept_ht_kwh": kept_ht_kwh,
        "kept_nt_kwh": kept_nt_kwh,
        "residual_kwh": residual_kwh,
    }


class HochTarifClock(unittest.TestCase):
    def test_monday_0600_is_hoch(self) -> None:
        self.assertTrue(is_hochtarif(datetime(2026, 9, 28, 6, 0, tzinfo=ZURICH)))

    def test_saturday_2159_is_hoch(self) -> None:
        self.assertTrue(is_hochtarif(datetime(2026, 9, 26, 21, 59, tzinfo=ZURICH)))

    def test_monday_0559_is_nieder(self) -> None:
        self.assertFalse(is_hochtarif(datetime(2026, 9, 28, 5, 59, tzinfo=ZURICH)))

    def test_saturday_2200_is_nieder(self) -> None:
        self.assertFalse(is_hochtarif(datetime(2026, 9, 26, 22, 0, tzinfo=ZURICH)))

    def test_sunday_1200_is_nieder(self) -> None:
        self.assertFalse(is_hochtarif(datetime(2026, 9, 27, 12, 0, tzinfo=ZURICH)))


class ResidualArithmetic(unittest.TestCase):
    def test_clamp_and_nonzero_residual(self) -> None:
        out = day_balance(
            solar_kwh=2.0,
            solar_ht_kwh=1.0,
            solar_nt_kwh=1.0,
            import_kwh=5.0,
            import_ht_kwh=5.0,
            import_nt_kwh=0.0,
            export_kwh=1.6,
            export_ht_kwh=1.4,
            export_nt_kwh=0.2,
        )
        self.assertEqual(out["kept_ht_kwh"], 0.0)
        self.assertAlmostEqual(out["kept_nt_kwh"], 0.8)
        self.assertNotEqual(out["residual_kwh"], 0.0)

    def test_zero_when_hours_match_and_no_clamp(self) -> None:
        out = day_balance(
            solar_kwh=2.0,
            solar_ht_kwh=1.0,
            solar_nt_kwh=1.0,
            import_kwh=5.0,
            import_ht_kwh=4.0,
            import_nt_kwh=1.0,
            export_kwh=0.5,
            export_ht_kwh=0.3,
            export_nt_kwh=0.2,
        )
        self.assertAlmostEqual(out["kept_ht_kwh"], 0.7)
        self.assertAlmostEqual(out["kept_nt_kwh"], 0.8)
        self.assertAlmostEqual(out["residual_kwh"], 0.0)


class FluxTaskContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.flux = TASK.read_text()
        cls.setup = SETUP.read_text()

    def test_inputs_and_predicate(self) -> None:
        self.assertIn("total_act", self.flux)
        self.assertIn("total_act_ret", self.flux)
        self.assertIn("yieldday", self.flux)
        self.assertIn(HOCH_PREDICATE, self.flux)
        self.assertIn('timezone.location(name: "Europe/Zurich")', self.flux)
        self.assertIn("else 0.0", self.flux)
        self.assertIn("residual_kwh", self.flux)
        self.assertNotIn("integral(", self.flux)
        self.assertNotIn("grid_import_kwh", self.flux)
        self.assertGreaterEqual(
            self.flux.count('timeSrc: "_start"'),
            4,
            "window _start is the hour/day stamp; range _start collapses every bar onto one time",
        )

    def test_setup_job_refuses_missing_counter(self) -> None:
        self.assertIn("total_act", self.setup)
        self.assertIn("100000", self.setup)
        self.assertRegex(self.setup, r"exit 1")
        self.assertIn("FATAL", self.setup)
        self.assertIn("Energy balance", self.setup)


if __name__ == "__main__":
    unittest.main()
