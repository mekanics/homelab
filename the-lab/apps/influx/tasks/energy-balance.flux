import "date"
import "timezone"

option location = timezone.location(name: "Europe/Zurich")
option task = {name: "Energy balance", every: 5m}

// Live check 2026-09-26: total_act 8942887.13 Wh, total_act_ret 1609741.78 Wh,
// yieldday 2634 Wh. Counters are Wh. Do not integrate watts.
stop = now()
rewrite_start = date.add(d: -3d, to: date.truncate(t: stop, unit: 1d))
lookback = date.add(d: -36h, to: rewrite_start)

is_hochtarif = (t) => date.weekDay(t: t) != 0 and date.hour(t: t) >= 6 and date.hour(t: t) < 22

meter_kwh = (raw, end_wh) =>
    if raw < -1000.0 then
        end_wh / 1000.0
    else if raw < 0.0 then
        0.0
    else
        raw / 1000.0

meter_hours = (field, out_field) =>
    from(bucket: "waid-bucket")
        |> range(start: lookback, stop: stop)
        |> filter(fn: (r) => r["_measurement"] == "mqtt_consumer" and r["_field"] == field)
        |> drop(columns: ["host", "topic"])
        |> group()
        |> aggregateWindow(every: 1h, fn: last, createEmpty: false, location: location, timeSrc: "_start")
        |> duplicate(column: "_value", as: "end_wh")
        |> difference(columns: ["_value"])
        |> filter(fn: (r) => r._time >= rewrite_start)
        |> map(
            fn: (r) =>
                ({
                    _time: r._time,
                    _value: meter_kwh(raw: r._value, end_wh: r.end_wh),
                    _field: out_field,
                    _measurement: "energy_hourly",
                }),
        )

hour_zeros = (out_field) =>
    from(bucket: "waid-bucket")
        |> range(start: rewrite_start, stop: stop)
        |> filter(
            fn: (r) => r["_measurement"] == "mqtt_consumer" and r["_field"] == "total_act_power",
        )
        |> drop(columns: ["host", "topic"])
        |> group()
        |> aggregateWindow(every: 1h, fn: last, createEmpty: true, location: location, timeSrc: "_start")
        |> map(
            fn: (r) =>
                ({
                    _time: r._time,
                    _value: 0.0,
                    _field: out_field,
                    _measurement: "energy_hourly",
                }),
        )

fill_hours = (field, out_field) =>
    union(tables: [meter_hours(field: field, out_field: out_field), hour_zeros(out_field: out_field)])
        |> group(columns: ["_time", "_field", "_measurement"])
        |> sum()
        |> map(
            fn: (r) =>
                ({
                    _time: r._time,
                    _value: r._value,
                    _field: out_field,
                    _measurement: "energy_hourly",
                }),
        )

solar_hours =
    from(bucket: "waid-bucket")
        |> range(start: lookback, stop: stop)
        |> filter(
            fn: (r) =>
                r["_measurement"] == "solar" and r["_field"] == "yieldday" and r.channel == "0",
        )
        |> drop(columns: ["host", "topic", "channel", "serial"])
        |> group()
        |> aggregateWindow(every: 1h, fn: last, createEmpty: true, location: location, timeSrc: "_start")
        |> fill(usePrevious: true)
        |> duplicate(column: "_value", as: "end_wh")
        |> difference(columns: ["_value"])
        |> filter(fn: (r) => r._time >= rewrite_start)
        |> map(
            fn: (r) =>
                ({
                    _time: r._time,
                    _value:
                        if r._value < 0.0 then
                            r.end_wh / 1000.0
                        else
                            r._value / 1000.0,
                    _field: "solar_kwh",
                    _measurement: "energy_hourly",
                }),
        )

hourly_written =
    union(
        tables: [
            solar_hours,
            fill_hours(field: "total_act", out_field: "import_kwh"),
            fill_hours(field: "total_act_ret", out_field: "export_kwh"),
        ],
    )
        |> to(bucket: "waid-bucket-downsampled", org: "waid")

meter_days = (field, out_field) =>
    from(bucket: "waid-bucket")
        |> range(start: lookback, stop: stop)
        |> filter(fn: (r) => r["_measurement"] == "mqtt_consumer" and r["_field"] == field)
        |> drop(columns: ["host", "topic"])
        |> group()
        |> aggregateWindow(every: 1d, fn: last, createEmpty: false, location: location, timeSrc: "_start")
        |> duplicate(column: "_value", as: "end_wh")
        |> difference(columns: ["_value"])
        |> filter(fn: (r) => r._time >= rewrite_start)
        |> map(
            fn: (r) =>
                ({
                    _time: r._time,
                    _value: meter_kwh(raw: r._value, end_wh: r.end_wh),
                    _field: out_field,
                    _measurement: "energy_balance",
                }),
        )

solar_days =
    from(bucket: "waid-bucket")
        |> range(start: rewrite_start, stop: stop)
        |> filter(
            fn: (r) =>
                r["_measurement"] == "solar" and r["_field"] == "yieldday" and r.channel == "0",
        )
        |> drop(columns: ["host", "topic", "channel", "serial"])
        |> group()
        |> aggregateWindow(every: 1d, fn: last, createEmpty: false, location: location, timeSrc: "_start")
        |> map(
            fn: (r) =>
                ({
                    _time: r._time,
                    _value: r._value / 1000.0,
                    _field: "solar_kwh",
                    _measurement: "energy_balance",
                }),
        )

ht_nt =
    hourly_written
        |> map(
            fn: (r) =>
                ({
                    _time: date.truncate(t: r._time, unit: 1d),
                    _value: r._value,
                    _field:
                        if r._field == "solar_kwh" then
                            if is_hochtarif(t: r._time) then
                                "solar_ht_kwh"
                            else
                                "solar_nt_kwh"
                        else if r._field == "import_kwh" then
                            if is_hochtarif(t: r._time) then
                                "import_ht_kwh"
                            else
                                "import_nt_kwh"
                        else if is_hochtarif(t: r._time) then
                            "export_ht_kwh"
                        else
                            "export_nt_kwh",
                    _measurement: "energy_balance",
                }),
        )
        |> group(columns: ["_time", "_field", "_measurement"])
        |> sum()

with_derived =
    union(
        tables: [
            solar_days,
            meter_days(field: "total_act", out_field: "import_kwh"),
            meter_days(field: "total_act_ret", out_field: "export_kwh"),
            ht_nt,
        ],
    )
        |> group()
        |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
        |> map(
            fn: (r) => {
                solar = if exists r.solar_kwh then r.solar_kwh else 0.0
                solar_ht = if exists r.solar_ht_kwh then r.solar_ht_kwh else 0.0
                solar_nt = if exists r.solar_nt_kwh then r.solar_nt_kwh else 0.0
                import_k = if exists r.import_kwh then r.import_kwh else 0.0
                import_ht = if exists r.import_ht_kwh then r.import_ht_kwh else 0.0
                import_nt = if exists r.import_nt_kwh then r.import_nt_kwh else 0.0
                export_k = if exists r.export_kwh then r.export_kwh else 0.0
                export_ht = if exists r.export_ht_kwh then r.export_ht_kwh else 0.0
                export_nt = if exists r.export_nt_kwh then r.export_nt_kwh else 0.0
                kept_ht = if solar_ht - export_ht > 0.0 then solar_ht - export_ht else 0.0
                kept_nt = if solar_nt - export_nt > 0.0 then solar_nt - export_nt else 0.0
                residual =
                    solar - kept_ht - kept_nt - export_k + (import_k - import_ht - import_nt)
                        +
                        (export_k - export_ht - export_nt)

                return {
                    _time: r._time,
                    solar_kwh: solar,
                    solar_ht_kwh: solar_ht,
                    solar_nt_kwh: solar_nt,
                    import_kwh: import_k,
                    import_ht_kwh: import_ht,
                    import_nt_kwh: import_nt,
                    export_kwh: export_k,
                    export_ht_kwh: export_ht,
                    export_nt_kwh: export_nt,
                    kept_ht_kwh: kept_ht,
                    kept_nt_kwh: kept_nt,
                    residual_kwh: residual,
                }
            },
        )

union(
    tables: [
        with_derived
            |> map(
                fn: (r) =>
                    ({
                        _time: r._time,
                        _value: r.solar_kwh,
                        _field: "solar_kwh",
                        _measurement: "energy_balance",
                    }),
            ),
        with_derived
            |> map(
                fn: (r) =>
                    ({
                        _time: r._time,
                        _value: r.solar_ht_kwh,
                        _field: "solar_ht_kwh",
                        _measurement: "energy_balance",
                    }),
            ),
        with_derived
            |> map(
                fn: (r) =>
                    ({
                        _time: r._time,
                        _value: r.solar_nt_kwh,
                        _field: "solar_nt_kwh",
                        _measurement: "energy_balance",
                    }),
            ),
        with_derived
            |> map(
                fn: (r) =>
                    ({
                        _time: r._time,
                        _value: r.import_kwh,
                        _field: "import_kwh",
                        _measurement: "energy_balance",
                    }),
            ),
        with_derived
            |> map(
                fn: (r) =>
                    ({
                        _time: r._time,
                        _value: r.import_ht_kwh,
                        _field: "import_ht_kwh",
                        _measurement: "energy_balance",
                    }),
            ),
        with_derived
            |> map(
                fn: (r) =>
                    ({
                        _time: r._time,
                        _value: r.import_nt_kwh,
                        _field: "import_nt_kwh",
                        _measurement: "energy_balance",
                    }),
            ),
        with_derived
            |> map(
                fn: (r) =>
                    ({
                        _time: r._time,
                        _value: r.export_kwh,
                        _field: "export_kwh",
                        _measurement: "energy_balance",
                    }),
            ),
        with_derived
            |> map(
                fn: (r) =>
                    ({
                        _time: r._time,
                        _value: r.export_ht_kwh,
                        _field: "export_ht_kwh",
                        _measurement: "energy_balance",
                    }),
            ),
        with_derived
            |> map(
                fn: (r) =>
                    ({
                        _time: r._time,
                        _value: r.export_nt_kwh,
                        _field: "export_nt_kwh",
                        _measurement: "energy_balance",
                    }),
            ),
        with_derived
            |> map(
                fn: (r) =>
                    ({
                        _time: r._time,
                        _value: r.kept_ht_kwh,
                        _field: "kept_ht_kwh",
                        _measurement: "energy_balance",
                    }),
            ),
        with_derived
            |> map(
                fn: (r) =>
                    ({
                        _time: r._time,
                        _value: r.kept_nt_kwh,
                        _field: "kept_nt_kwh",
                        _measurement: "energy_balance",
                    }),
            ),
        with_derived
            |> map(
                fn: (r) =>
                    ({
                        _time: r._time,
                        _value: r.residual_kwh,
                        _field: "residual_kwh",
                        _measurement: "energy_balance",
                    }),
            ),
    ],
)
    |> to(bucket: "waid-bucket-downsampled", org: "waid")
