import "date"
import "timezone"

option location = timezone.location(name: "Europe/Zurich")
option task = {name: "Downsampling yieldday", every: 1h}

// Closed days only. Hourly reruns rewrite the last few days so a missed hour
// or a compaction stall does not leave a permanent hole.
stop = date.truncate(t: now(), unit: 1d)
start = date.add(d: -3d, to: stop)

from(bucket: "waid-bucket")
    |> range(start: start, stop: stop)
    |> filter(
        fn: (r) =>
            r["_measurement"] == "solar" and r["_field"] == "yieldday" and r["channel"] == "0",
    )
    |> drop(columns: ["host"])
    |> aggregateWindow(every: 1d, fn: last, createEmpty: false, location: location)
    |> to(bucket: "waid-bucket-downsampled", org: "waid")
