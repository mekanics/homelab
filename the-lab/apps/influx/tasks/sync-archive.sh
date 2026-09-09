#!/bin/sh
# Upsert downsample tasks, backfill daily grid kWh if the archive is thin,
# then set waid-bucket retention to 365d. Retention is last on purpose:
# expiring raw data before the archive exists would destroy YoY history.
set -eu

: "${INFLUX_HOST:?}"
: "${INFLUX_TOKEN:?}"
: "${INFLUX_ORG:=waid}"

TASKS_DIR="${TASKS_DIR:-/tasks}"

upsert_task() {
  name="$1"
  file="$2"
  id="$(influx task list --org "${INFLUX_ORG}" --hide-headers | awk -v n="${name}" 'index($0, n) { print $1; exit }')"
  if [ -n "${id}" ]; then
    echo "Updating task '${name}' (${id})"
    influx task update --id "${id}" --file "${file}" >/dev/null
  else
    echo "Creating task '${name}'"
    influx task create --org "${INFLUX_ORG}" --file "${file}" >/dev/null
  fi
}

energy_point_count() {
  influx query --org "${INFLUX_ORG}" --raw '
from(bucket: "waid-bucket-downsampled")
  |> range(start: 2023-10-01T00:00:00Z)
  |> filter(fn: (r) => r["_measurement"] == "energy_daily" and r["_field"] == "grid_net_kwh")
  |> group()
  |> count()
' | awk -F ',' 'BEGIN { n=0 } $0 ~ /^,/ { gsub(/[^0-9]/, "", $NF); if ($NF != "") n=$NF } END { print n+0 }'
}

backfill_month() {
  start="$1"
  stop="$2"
  echo "  Backfilling energy_daily ${start} → ${stop}"
  influx query --org "${INFLUX_ORG}" "
import \"timezone\"
option location = timezone.location(name: \"Europe/Zurich\")
from(bucket: \"waid-bucket\")
  |> range(start: ${start}, stop: ${stop})
  |> filter(fn: (r) => r[\"_measurement\"] == \"mqtt_consumer\" and r[\"_field\"] == \"total_act_power\")
  |> drop(columns: [\"host\", \"topic\"])
  |> group()
  |> sort(columns: [\"_time\"])
  |> window(every: 1d, location: location)
  |> integral(unit: 1h)
  |> map(fn: (r) => ({ r with
      _time: r._stop,
      _value: r._value / 1000.0,
      _field: \"grid_net_kwh\",
      _measurement: \"energy_daily\"
    }))
  |> window(every: inf)
  |> to(bucket: \"waid-bucket-downsampled\", org: \"${INFLUX_ORG}\")
" >/dev/null
}

echo "Waiting for InfluxDB..."
i=0
while ! influx bucket list --org "${INFLUX_ORG}" >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "${i}" -ge 30 ]; then
    echo "FATAL: InfluxDB did not become ready"
    exit 1
  fi
  sleep 2
done

upsert_task "Downsampling yieldday" "${TASKS_DIR}/downsample-yieldday.flux"
upsert_task "Downsampling energy daily" "${TASKS_DIR}/downsample-energy-daily.flux"

count="$(energy_point_count)"
echo "energy_daily points since 2023-10: ${count}"

# ~90 days is a thin archive (the 7d probe, or a stalled first run).
# A full history is ~700–1000 daily points.
if [ "${count}" -lt 90 ]; then
  echo "Archive is thin; backfilling monthly from 2023-10..."
  y=2023
  m=10
  ym="$(printf '%04d%02d' "${y}" "${m}")"
  end_ym="$(date -u +%Y%m)"
  while [ "${ym}" -le "${end_ym}" ]; do
    next_m=$((m + 1))
    next_y=${y}
    if [ "${next_m}" -eq 13 ]; then
      next_m=1
      next_y=$((y + 1))
    fi
    start="$(printf '%04d-%02d-01T00:00:00Z' "${y}" "${m}")"
    stop="$(printf '%04d-%02d-01T00:00:00Z' "${next_y}" "${next_m}")"
    backfill_month "${start}" "${stop}"
    y=${next_y}
    m=${next_m}
    ym="$(printf '%04d%02d' "${y}" "${m}")"
  done
  echo "Backfill finished. points=$(energy_point_count)"
else
  echo "Archive already populated; skipping backfill."
fi

bucket_id="$(influx bucket list --org "${INFLUX_ORG}" --name waid-bucket --hide-headers | awk '{ print $1; exit }')"
if [ -z "${bucket_id}" ]; then
  echo "FATAL: waid-bucket not found"
  exit 1
fi
echo "Setting waid-bucket (${bucket_id}) retention to 365d"
influx bucket update --id "${bucket_id}" --retention 365d >/dev/null
echo "Done."
