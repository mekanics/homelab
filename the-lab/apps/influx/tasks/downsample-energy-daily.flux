import "date"
import "timezone"

option location = timezone.location(name: "Europe/Zurich")
option task = {name: "Downsampling energy daily", every: 1h}

// Closed Zurich days only. total_act_power is signed watts (import +, export -).
// integral(unit: 1h) → watt-hours; divide by 1000 → kWh.
stop = date.truncate(t: now(), unit: 1d)
start = date.add(d: -3d, to: stop)

from(bucket: "waid-bucket")
    |> range(start: start, stop: stop)
    |> filter(
        fn: (r) => r["_measurement"] == "mqtt_consumer" and r["_field"] == "total_act_power",
    )
    |> drop(columns: ["host", "topic"])
    |> group()
    |> sort(columns: ["_time"])
    |> window(every: 1d, location: location)
    |> integral(unit: 1h)
    |> map(
        fn: (r) =>
            ({r with
                _time: r._stop,
                _value: r._value / 1000.0,
                _field: "grid_net_kwh",
                _measurement: "energy_daily",
            }),
    )
    |> window(every: inf)
    |> to(bucket: "waid-bucket-downsampled", org: "waid")
