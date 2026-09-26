#!/bin/sh
# Upsert downsample tasks, backfill daily grid kWh if the archive is thin,
# then set waid-bucket retention to 365d. Retention is last on purpose:
# expiring raw data before the archive exists would destroy YoY history.
#
# energy_daily (integral of watts, Year comparison) per closed Zurich day:
#   grid_net_kwh, grid_import_kwh, grid_export_kwh
# energy_balance / energy_hourly (Shelly counters + yieldday) are a separate
# archive. Do not overwrite energy_daily.
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

field_point_count() {
  field="$1"
  influx query --org "${INFLUX_ORG}" --raw "
from(bucket: \"waid-bucket-downsampled\")
  |> range(start: 2023-10-01T00:00:00Z)
  |> filter(fn: (r) => r[\"_measurement\"] == \"energy_daily\" and r[\"_field\"] == \"${field}\")
  |> group()
  |> count()
" | awk -F ',' 'BEGIN { n=0 } $0 ~ /^,/ { gsub(/[^0-9]/, "", $NF); if ($NF != "") n=$NF } END { print n+0 }'
}

# Backfill all three energy_daily fields for one calendar month.
backfill_month() {
  start="$1"
  stop="$2"
  echo "  Backfilling energy_daily ${start} → ${stop}"
  influx query --org "${INFLUX_ORG}" "
import \"timezone\"
option location = timezone.location(name: \"Europe/Zurich\")

base = from(bucket: \"waid-bucket\")
  |> range(start: ${start}, stop: ${stop})
  |> filter(fn: (r) => r[\"_measurement\"] == \"mqtt_consumer\" and r[\"_field\"] == \"total_act_power\")
  |> drop(columns: [\"host\", \"topic\"])
  |> group()
  |> sort(columns: [\"_time\"])

net = base
  |> window(every: 1d, location: location)
  |> integral(unit: 1h)
  |> map(fn: (r) => ({
      _time: r._stop,
      _value: r._value / 1000.0,
      _field: \"grid_net_kwh\",
      _measurement: \"energy_daily\"
    }))

grid_import = base
  |> map(fn: (r) => ({r with _value: if r._value > 0.0 then r._value else 0.0}))
  |> window(every: 1d, location: location)
  |> integral(unit: 1h)
  |> map(fn: (r) => ({
      _time: r._stop,
      _value: r._value / 1000.0,
      _field: \"grid_import_kwh\",
      _measurement: \"energy_daily\"
    }))

grid_export = base
  |> map(fn: (r) => ({r with _value: if r._value < 0.0 then -r._value else 0.0}))
  |> window(every: 1d, location: location)
  |> integral(unit: 1h)
  |> map(fn: (r) => ({
      _time: r._stop,
      _value: r._value / 1000.0,
      _field: \"grid_export_kwh\",
      _measurement: \"energy_daily\"
    }))

union(tables: [net, grid_import, grid_export])
  |> to(bucket: \"waid-bucket-downsampled\", org: \"${INFLUX_ORG}\")
" >/dev/null
}

# Run backfill from START_YM (YYYYMM) up to the current month.
run_backfill() {
  start_y="$1"
  start_m="$2"
  label="$3"
  echo "Archive is ${label}; backfilling monthly from $(printf '%04d-%02d' "${start_y}" "${start_m}")..."
  y="${start_y}"
  m="${start_m}"
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
  echo "Backfill finished."
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

last_total_act() {
  influx query --org "${INFLUX_ORG}" --raw "
from(bucket: \"waid-bucket\")
  |> range(start: -24h)
  |> filter(fn: (r) => r[\"_measurement\"] == \"mqtt_consumer\" and r[\"_field\"] == \"total_act\")
  |> last()
  |> keep(columns: [\"_value\"])
" | awk -F ',' '$0 ~ /^,/ && $NF ~ /[0-9]/ { print $NF; exit }'
}

total_act_count_24h() {
  influx query --org "${INFLUX_ORG}" --raw "
from(bucket: \"waid-bucket\")
  |> range(start: -24h)
  |> filter(fn: (r) => r[\"_measurement\"] == \"mqtt_consumer\" and r[\"_field\"] == \"total_act\")
  |> group()
  |> count()
" | awk -F ',' 'BEGIN { n=0 } $0 ~ /^,/ { gsub(/[^0-9]/, "", $NF); if ($NF != "") n=$NF } END { print n+0 }'
}

balance_point_count() {
  influx query --org "${INFLUX_ORG}" --raw "
from(bucket: \"waid-bucket-downsampled\")
  |> range(start: -365d)
  |> filter(fn: (r) => r[\"_measurement\"] == \"energy_balance\" and r[\"_field\"] == \"solar_kwh\")
  |> group()
  |> count()
" | awk -F ',' 'BEGIN { n=0 } $0 ~ /^,/ { gsub(/[^0-9]/, "", $NF); if ($NF != "") n=$NF } END { print n+0 }'
}

# Run energy-balance.flux as a query over [start, stop).
backfill_balance_month() {
  start="$1"
  stop="$2"
  echo "  Backfilling energy_balance ${start} → ${stop}"
  awk -v s="${start}" -v e="${stop}" '
    /^option task/ { next }
    /^stop = now\(\)/ { print "stop = time(v: \"" e "\")"; next }
    /^rewrite_start = / { print "rewrite_start = time(v: \"" s "\")"; next }
    { print }
  ' "${TASKS_DIR}/energy-balance.flux" | influx query --org "${INFLUX_ORG}" >/dev/null
}

run_balance_backfill() {
  start_y="$1"
  start_m="$2"
  echo "energy_balance is thin; backfilling monthly from $(printf '%04d-%02d' "${start_y}" "${start_m}")..."
  y="${start_y}"
  m="${start_m}"
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
    backfill_balance_month "${start}" "${stop}"
    y=${next_y}
    m=${next_m}
    ym="$(printf '%04d%02d' "${y}" "${m}")"
  done
  echo "energy_balance backfill finished."
}

act_count="$(total_act_count_24h)"
act_last="$(last_total_act)"
echo "total_act last 24h: count=${act_count} last=${act_last}"
if [ "${act_count}" -eq 0 ]; then
  echo "FATAL: no total_act in the last 24h"
  exit 1
fi
if ! awk -v v="${act_last}" 'BEGIN { exit !(v+0 >= 100000) }'; then
  echo "FATAL: total_act last=${act_last} is below 100000; expected Wh"
  exit 1
fi

upsert_task "Downsampling yieldday" "${TASKS_DIR}/downsample-yieldday.flux"
upsert_task "Downsampling energy daily" "${TASKS_DIR}/downsample-energy-daily.flux"
upsert_task "Energy balance" "${TASKS_DIR}/energy-balance.flux"

net_count="$(field_point_count grid_net_kwh)"
import_count="$(field_point_count grid_import_kwh)"
echo "energy_daily points since 2023-10: net=${net_count} import=${import_count}"

# ~90 days is a thin net archive (initial probe or a stalled first run).
if [ "${net_count}" -lt 90 ]; then
  run_backfill 2023 10 "thin (net=${net_count})"
  echo "net=$(field_point_count grid_net_kwh) import=$(field_point_count grid_import_kwh)"
# import/export fields missing means old version of the task ran without them.
elif [ "${import_count}" -lt 90 ]; then
  run_backfill 2023 10 "missing import/export (import=${import_count})"
  echo "net=$(field_point_count grid_net_kwh) import=$(field_point_count grid_import_kwh)"
else
  echo "Archive already populated; skipping backfill."
fi

balance_count="$(balance_point_count)"
echo "energy_balance solar_kwh points in 365d: ${balance_count}"
if [ "${balance_count}" -lt 30 ]; then
  start_secs=$(($(date -u +%s) - 365 * 86400))
  start_y="$(date -u -d "@${start_secs}" +%Y)"
  start_m="$(date -u -d "@${start_secs}" +%m)"
  start_m="${start_m#0}"
  run_balance_backfill "${start_y}" "${start_m}"
  echo "energy_balance solar_kwh points: $(balance_point_count)"
else
  echo "energy_balance already populated; skipping backfill."
fi

bucket_id="$(influx bucket list --org "${INFLUX_ORG}" --name waid-bucket --hide-headers | awk '{ print $1; exit }')"
if [ -z "${bucket_id}" ]; then
  echo "FATAL: waid-bucket not found"
  exit 1
fi
echo "Setting waid-bucket (${bucket_id}) retention to 365d"
influx bucket update --id "${bucket_id}" --retention 365d >/dev/null
echo "Done."
