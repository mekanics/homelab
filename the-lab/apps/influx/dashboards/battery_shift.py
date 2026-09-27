"""Counterfactual AC-coupled battery walk over closed hours.

Kept still assumes no battery. This module is the what-if.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

ZURICH = ZoneInfo("Europe/Zurich")


def is_hochtarif(t: datetime) -> bool:
    """Europe/Zurich Hoch tarif: Monday–Saturday, hour in [6, 22). Sunday is 0."""
    local = t.astimezone(ZURICH)
    return local.weekday() != 6 and local.hour >= 6 and local.hour < 22


@dataclass(frozen=True)
class Hour:
    time: datetime
    import_kwh: float
    export_kwh: float


@dataclass(frozen=True)
class ShiftResult:
    charged_ht_kwh: float
    charged_nt_kwh: float
    shifted_ht_kwh: float
    shifted_nt_kwh: float
    leftover_export_kwh: float
    leftover_import_kwh: float
    end_soc_kwh: float


def shift_hours(
    hours: list[Hour],
    *,
    usable_kwh: float,
    eta: float,
) -> ShiftResult:
    ordered = sorted(hours, key=lambda h: h.time)
    charged_ht = 0.0
    charged_nt = 0.0
    shifted_ht = 0.0
    shifted_nt = 0.0
    leftover_export = 0.0
    leftover_import = 0.0
    soc = 0.0
    dead = usable_kwh <= 0.0 or eta <= 0.0

    for hour in ordered:
        export = hour.export_kwh if hour.export_kwh > 0.0 else 0.0
        imported = hour.import_kwh if hour.import_kwh > 0.0 else 0.0
        hoch = is_hochtarif(hour.time)

        take = 0.0
        if not dead:
            room = usable_kwh - soc
            take = min(export, room / eta)
            soc += take * eta
        leftover_export += export - take
        if hoch:
            charged_ht += take
        else:
            charged_nt += take

        give = 0.0
        if not dead:
            give = min(imported, soc)
            soc -= give
        leftover_import += imported - give
        if hoch:
            shifted_ht += give
        else:
            shifted_nt += give

    return ShiftResult(
        charged_ht_kwh=charged_ht,
        charged_nt_kwh=charged_nt,
        shifted_ht_kwh=shifted_ht,
        shifted_nt_kwh=shifted_nt,
        leftover_export_kwh=leftover_export,
        leftover_import_kwh=leftover_import,
        end_soc_kwh=soc,
    )


def saved_chf(
    *,
    shifted_ht_kwh: float,
    shifted_nt_kwh: float,
    charged_ht_kwh: float,
    charged_nt_kwh: float,
    buy_ht: float,
    buy_nt: float,
    feed_ht: float,
    feed_nt: float,
) -> float:
    return (
        shifted_ht_kwh * buy_ht
        + shifted_nt_kwh * buy_nt
        - charged_ht_kwh * feed_ht
        - charged_nt_kwh * feed_nt
    )


def payback_years(saved: float, battery_chf: float) -> float | None:
    if saved <= 0.0:
        return None
    return battery_chf / saved


def max_price(saved: float, years: float) -> float | None:
    if saved <= 0.0:
        return None
    return saved * years
