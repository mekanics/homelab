#!/usr/bin/env python3
"""Assert every OpenClaw container runs as the uid the NFS home reports.

The Synology export maps all client uids to admin, so files on the home
share are owned by 1024. OpenClaw blocks npm-installed plugins owned by
any uid other than its own or root ("suspicious ownership"), and fs-safe
requires the prepared /tmp to be owned by the process that uses it. So
init-config, init-doctor and the gateway must all run as 1024.
"""

from __future__ import annotations

import subprocess
import sys

from test_state_pvc_backup_labels import deployment_doc, render

NFS_OWNER_UID = "1024"


def container_uids(deployment: str) -> dict[str, str]:
    out = subprocess.run(
        [
            "yq",
            "-r",
            '.spec.template.spec.["initContainers", "containers"][] | .name + "=" + (.securityContext.runAsUser | tostring)',
        ],
        input=deployment,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return dict(line.split("=", 1) for line in out.splitlines() if line)


def main() -> int:
    uids = container_uids(deployment_doc(render()))
    expected = {"init-config", "init-doctor", "gateway"}
    missing = expected - uids.keys()
    if missing:
        print("containers missing from render:", sorted(missing), file=sys.stderr)
        return 1
    wrong = {name: uid for name, uid in uids.items() if uid != NFS_OWNER_UID}
    if wrong:
        print(f"containers not running as {NFS_OWNER_UID}:", wrong, file=sys.stderr)
        return 1
    print(f"all containers run as {NFS_OWNER_UID}:", sorted(uids))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
