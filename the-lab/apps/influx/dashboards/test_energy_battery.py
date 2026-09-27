#!/usr/bin/env python3
"""Oracle for the Battery what-if walk."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from battery_shift import Hour, max_price, payback_years, saved_chf, shift_hours

ZURICH = ZoneInfo("Europe/Zurich")


def zdt(hour: int, day: int = 28) -> datetime:
    """Monday 28 Sep 2026 in Zurich, so 06:00–22:00 is Hoch tarif."""
    return datetime(2026, 9, day, hour, tzinfo=ZURICH)


FIXTURE = [
    Hour(time=zdt(10), import_kwh=0.0, export_kwh=1.0),
    Hour(time=zdt(14), import_kwh=0.2, export_kwh=1.0),
    Hour(time=zdt(22), import_kwh=1.0, export_kwh=0.0),
    Hour(time=zdt(23), import_kwh=0.0, export_kwh=0.3),
]


class ShiftHoursOracle(unittest.TestCase):
    def test_fixture_charges_then_discharges_and_carries_overnight(self) -> None:
        out = shift_hours(FIXTURE, usable_kwh=2.0, eta=0.9)
        self.assertAlmostEqual(out.charged_ht_kwh, 2.0)
        self.assertAlmostEqual(out.charged_nt_kwh, 0.3)
        self.assertAlmostEqual(out.shifted_ht_kwh, 0.2)
        self.assertAlmostEqual(out.shifted_nt_kwh, 1.0)
        self.assertAlmostEqual(out.leftover_export_kwh, 0.0)
        self.assertAlmostEqual(out.leftover_import_kwh, 0.0)
        self.assertAlmostEqual(out.end_soc_kwh, 0.87)

    def test_capacity_binds_charged_energy(self) -> None:
        hours = [Hour(time=zdt(10), import_kwh=0.0, export_kwh=1.0)]
        out = shift_hours(hours, usable_kwh=0.5, eta=1.0)
        self.assertAlmostEqual(out.charged_ht_kwh, 0.5)
        self.assertAlmostEqual(out.leftover_export_kwh, 0.5)
        self.assertAlmostEqual(out.end_soc_kwh, 0.5)

    def test_eta_is_applied_on_charge(self) -> None:
        hours = [
            Hour(time=zdt(10), import_kwh=0.0, export_kwh=1.0),
            Hour(time=zdt(22), import_kwh=1.0, export_kwh=0.0),
        ]
        out = shift_hours(hours, usable_kwh=2.0, eta=0.9)
        self.assertAlmostEqual(out.charged_ht_kwh, 1.0)
        self.assertAlmostEqual(out.shifted_nt_kwh, 0.9)
        self.assertAlmostEqual(out.leftover_import_kwh, 0.1)
        self.assertAlmostEqual(out.end_soc_kwh, 0.0)

    def test_zero_pack_shifts_nothing(self) -> None:
        for usable, eta in ((0.0, 0.9), (2.0, 0.0), (-1.0, 0.9), (2.0, -0.1)):
            out = shift_hours(FIXTURE, usable_kwh=usable, eta=eta)
            self.assertEqual(out.shifted_ht_kwh, 0.0, (usable, eta))
            self.assertEqual(out.shifted_nt_kwh, 0.0, (usable, eta))
            self.assertAlmostEqual(out.leftover_export_kwh, 2.3, msg=(usable, eta))

    def test_sunday_noon_is_nieder(self) -> None:
        hours = [
            Hour(time=zdt(12, day=27), import_kwh=0.0, export_kwh=1.0),
            Hour(time=zdt(13, day=27), import_kwh=1.0, export_kwh=0.0),
        ]
        out = shift_hours(hours, usable_kwh=2.0, eta=1.0)
        self.assertAlmostEqual(out.charged_nt_kwh, 1.0)
        self.assertAlmostEqual(out.charged_ht_kwh, 0.0)
        self.assertAlmostEqual(out.shifted_nt_kwh, 1.0)
        self.assertAlmostEqual(out.shifted_ht_kwh, 0.0)


class MoneyHelper(unittest.TestCase):
    def test_saved_is_shifted_buy_minus_charged_feed(self) -> None:
        saved = saved_chf(
            shifted_ht_kwh=0.9,
            shifted_nt_kwh=0.0,
            charged_ht_kwh=1.0,
            charged_nt_kwh=0.0,
            buy_ht=0.2625,
            buy_nt=0.1590,
            feed_ht=0.1050,
            feed_nt=0.0645,
        )
        self.assertAlmostEqual(saved, 0.13125)

    def test_payback_is_dash_when_saved_is_zero(self) -> None:
        self.assertIsNone(payback_years(0.0, battery_chf=2000.0))
        self.assertIsNone(payback_years(-0.1, battery_chf=2000.0))
        self.assertIsNone(max_price(0.0, years=10.0))
        self.assertAlmostEqual(payback_years(200.0, battery_chf=2000.0), 10.0)
        self.assertAlmostEqual(max_price(200.0, years=10.0), 2000.0)


if __name__ == "__main__":
    unittest.main()
