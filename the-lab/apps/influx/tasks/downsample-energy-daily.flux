import "date"
import "timezone"

option location = timezone.location(name: "Europe/Zurich")
option task = {name: "Downsampling energy daily", every: 1h}

// Closed Zurich days only. total_act_power is signed watts (import +, export -).
// integral(unit: 1h) → watt-hours; divide by 1000 → kWh.
// Three fields are written per day:
//   grid_net_kwh    — net signed energy (existing; used by Year comparison)
//   grid_import_kwh — energy drawn from the grid (positive half)
//   grid_export_kwh — energy fed into the grid (negative half, stored positive)
stop = date.truncate(t: now(), unit: 1d)
start = date.add(d: -3d, to: stop)

base = from(bucket: "waid-bucket")
    |> range(start: start, stop: stop)
    |> filter(
        fn: (r) => r["_measurement"] == "mqtt_consumer" and r["_field"] == "total_act_power",
    )
    |> drop(columns: ["host", "topic"])
    |> group()
    |> sort(columns: ["_time"])

// Net signed kWh (import positive, export negative).
net = base
    |> window(every: 1d, location: location)
    |> integral(unit: 1h)
    |> map(
        fn: (r) =>
            ({
                _time: r._stop,
                _value: r._value / 1000.0,
                _field: "grid_net_kwh",
                _measurement: "energy_daily",
            }),
    )

// Grid import only (clamp export to zero before integrating).
grid_import = base
    |> map(fn: (r) => ({r with _value: if r._value > 0.0 then r._value else 0.0}))
    |> window(every: 1d, location: location)
    |> integral(unit: 1h)
    |> map(
        fn: (r) =>
            ({
                _time: r._stop,
                _value: r._value / 1000.0,
                _field: "grid_import_kwh",
                _measurement: "energy_daily",
            }),
    )

// Grid export only (clamp import to zero, negate so the value is positive).
grid_export = base
    |> map(fn: (r) => ({r with _value: if r._value < 0.0 then -r._value else 0.0}))
    |> window(every: 1d, location: location)
    |> integral(unit: 1h)
    |> map(
        fn: (r) =>
            ({
                _time: r._stop,
                _value: r._value / 1000.0,
                _field: "grid_export_kwh",
                _measurement: "energy_daily",
            }),
    )

union(tables: [net, grid_import, grid_export])
    |> to(bucket: "waid-bucket-downsampled", org: "waid")
