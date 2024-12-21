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

## High Availability Configuration

The cluster uses kube-vip for high availability of the control plane. The configuration includes:

- Fast leader election (3 second timeout)
- Frequent health checks (5 second intervals)
- Load balancing enabled for control plane traffic
- Prometheus metrics exposed for monitoring

If a master node fails, a new leader will be elected within 3-5 seconds to maintain control plane availability.
