#!/usr/bin/env python3
"""Assert the gateway memory alerts fire against the series the cluster has.

Kubelet exports container_memory_working_set_bytes twice per container,
from /metrics/cadvisor and /metrics/resource, with identical namespace,
pod and container labels. A one-to-one join on those labels then fails
with "duplicate time series" on every evaluation and the alert never
fires. The input below carries both series, as the cluster does.

cAdvisor's container_oom_events_total stays 0 here even across real
OOM kills, so the OOM alert reads kube-state-metrics instead.

Runs vmalert-tool from PATH, else the Docker image pinned to the
cluster's VictoriaMetrics version.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

CHART_DIR = Path(__file__).resolve().parent
RULE_TEMPLATE = "prometheusrule.yaml"
VMALERT_TOOL_IMAGE = "victoriametrics/vmalert-tool:v1.152.0"

GIB = 2**30
LIMIT = 5 * GIB
LIMIT_TEXT = "5Gi"
POD = "openclaw-abc123-xyz"
TARGET = {"namespace": "openclaw", "pod": POD, "container": "gateway"}

ANNOTATIONS = {
    "warning": {
        "summary": f"OpenClaw gateway {POD} above 80% of its memory limit",
        "description": "Working set is {pct} of the " + LIMIT_TEXT + " limit for 2m.",
    },
    "critical": {
        "summary": f"OpenClaw gateway {POD} above 90% of its memory limit — OOM likely",
        "description": (
            "Working set is {pct} of the " + LIMIT_TEXT + " limit for 2m. "
            "An OOM kill restarts the gateway mid-write and interrupts the sqlite WAL. "
            "Reduce concurrent subagent load."
        ),
    },
}


def labels(name: str, **extra: str) -> str:
    merged = {**TARGET, **extra}
    body = ",".join(f'{k}="{v}"' for k, v in merged.items())
    return f"{name}{{{body}}}"


def working_set(gib: float, minutes: int) -> list[dict]:
    samples = f"{int(gib * GIB)}x{minutes * 2}"
    return [
        {
            "series": labels(
                "container_memory_working_set_bytes",
                job="kubelet",
                metrics_path=path,
            ),
            "values": samples,
        }
        for path in ("/metrics/cadvisor", "/metrics/resource")
    ]


def limit(minutes: int) -> dict:
    return {
        "series": labels(
            "kube_pod_container_resource_limits",
            job="kube-state-metrics",
            resource="memory",
            unit="byte",
        ),
        "values": f"{LIMIT}x{minutes * 2}",
    }


def pressure(severity: str, pct: str) -> dict:
    text = ANNOTATIONS[severity]
    return {
        "exp_labels": {**TARGET, "severity": severity},
        "exp_annotations": {
            "summary": text["summary"],
            "description": text["description"].format(pct=pct),
        },
    }


def pressure_case(gib: float, expected: list[str]) -> dict:
    pct = f"{round(gib * GIB / LIMIT * 100)}%"
    return {
        "interval": "30s",
        "input_series": [*working_set(gib, 10), limit(10)],
        "alert_rule_test": [
            {
                "eval_time": "5m",
                "groupname": "openclaw",
                "alertname": "OpenClawGatewayMemoryPressure",
                "exp_alerts": [pressure(s, pct) for s in expected],
            }
        ],
    }


def oom_case(reason: str, expected: bool) -> dict:
    restart = labels("kube_pod_container_status_restarts_total", job="kube-state-metrics")
    terminated = labels(
        "kube_pod_container_status_last_terminated_reason",
        job="kube-state-metrics",
        reason=reason,
    )
    return {
        "interval": "30s",
        "input_series": [
            {"series": restart, "values": "0x10 1x10"},
            {"series": terminated, "values": "_x10 1x10"},
        ],
        "alert_rule_test": [
            {
                "eval_time": "7m",
                "groupname": "openclaw",
                "alertname": "OpenClawGatewayOOMKilled",
                "exp_alerts": (
                    [
                        {
                            "exp_labels": {
                                **TARGET,
                                "job": "kube-state-metrics",
                                "severity": "critical",
                            },
                            "exp_annotations": {
                                "summary": f"OpenClaw gateway {POD} was OOM-killed",
                                "description": (
                                    f"The gateway hit its {LIMIT_TEXT} memory limit "
                                    "and restarted within the last 10m."
                                ),
                            },
                        }
                    ]
                    if expected
                    else []
                ),
            }
        ],
    }


def render_rule_groups() -> str:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "Chart.yaml").write_text("apiVersion: v2\nname: openclaw-alerts\nversion: 0.0.0\n")
        (work / "values.yaml").write_bytes((CHART_DIR / "values.yaml").read_bytes())
        (work / "templates").mkdir()
        shutil.copy(CHART_DIR / "templates" / RULE_TEMPLATE, work / "templates" / RULE_TEMPLATE)
        built = subprocess.run(
            ["helm", "template", "openclaw", str(work), "--namespace", "openclaw"],
            check=True,
            capture_output=True,
            text=True,
        )
    lines = built.stdout.splitlines()
    spec = lines.index("spec:")
    return "\n".join(line.removeprefix("  ") for line in lines[spec + 1 :]) + "\n"


def vmalert_tool(work: Path) -> list[str]:
    if shutil.which("vmalert-tool"):
        return ["vmalert-tool", "unittest", f"--files={work / 'tests.yaml'}"]
    return [
        "docker", "run", "--rm",
        "-v", f"{work}:/work",
        VMALERT_TOOL_IMAGE,
        "unittest", "--files=/work/tests.yaml",
    ]


def main() -> int:
    tests = {
        "rule_files": ["rules.yaml"],
        "evaluation_interval": "30s",
        "tests": [
            pressure_case(2.5, []),
            pressure_case(4.25, ["warning"]),
            pressure_case(4.75, ["warning", "critical"]),
            oom_case("OOMKilled", True),
            oom_case("Error", False),
        ],
    }
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "rules.yaml").write_text(render_rule_groups())
        (work / "tests.yaml").write_text(json.dumps(tests, indent=2))
        result = subprocess.run(vmalert_tool(work), capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout, result.stderr, sep="\n", file=sys.stderr)
        print("openclaw memory alerts failed vmalert-tool unittest", file=sys.stderr)
        return 1
    print("openclaw memory alerts ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
