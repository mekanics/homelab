# Homelab with Kubernetes

## Hosts inventory

All hosts are defined in `src/inventory.yml`.

## Commands

### `make ping`

Test connectivity to inventory hosts.

### `make facts`

Gather and display facts about inventory hosts.

### `make lint`

Run Ansible Lint against the playbooks.

### `make host-bootstrap`

Initializes the remote hosts that comprise the cluster.
