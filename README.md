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

## Node Labeling Strategy

The cluster uses a comprehensive node labeling strategy to optimize workload placement based on Raspberry Pi hardware capabilities. This ensures that resource-intensive workloads (databases, storage services) are scheduled on appropriate nodes.

### Label Schema

All nodes are automatically labeled during k3s installation based on their configuration in `src/inventory.yml`:

#### Hardware Labels

- `node.homelab.io/performance: high|mid|low`

  - Indicates CPU and RAM capacity
  - High: Raspberry Pi 5 with 8GB RAM
  - Mid: Raspberry Pi 4 with 4GB RAM
  - Low: Older models

- `node.homelab.io/storage-type: ssd|mmc`

  - Storage backend type
  - SSD: Nodes with SSD or NVMe storage
  - MMC: Nodes with SD card storage

- `node.homelab.io/storage-tier: fast|standard`

  - Storage performance classification
  - Fast: SSD-backed nodes suitable for databases
  - Standard: SD card backed nodes

- `node.homelab.io/arch: arm64`
  - CPU architecture identifier

#### Storage Labels (Longhorn)

- `node.longhorn.io/create-default-disk: "true"`
  - Enables automatic Longhorn disk creation
  - Only nodes with this label will have Longhorn storage configured

### Workload Placement Guidelines

Workloads are configured with node affinity to prefer appropriate nodes:

#### Database Workloads

Database and stateful services prefer high-performance nodes with SSD storage:

- InfluxDB: Prefers high-performance, SSD nodes
- PostgreSQL (CloudNative-PG): Prefers high-performance, SSD nodes
- Valkey/Redis: Prefers high-performance, SSD nodes

#### Compute Workloads

Application workloads with moderate resource requirements:

- n8n main application: Prefers high-performance, SSD nodes
- n8n workers: Accepts any SSD node

#### Monitoring & Storage

- Prometheus: Prefers high-performance, SSD nodes (metrics database)
- Grafana: Prefers SSD nodes (dashboard storage)
- Longhorn components: Required to run on SSD nodes

### Adding New Nodes

When adding a new node to the cluster:

1. **Update inventory** (`src/inventory.yml`):

```yaml
new-node.local:
  ansible_host: 192.168.10.XX
  mac: 'xx:xx:xx:xx:xx:xx'
  ansible_connection: ssh
  performance: high|mid|low
  disctype: 'ssd|mmc'
  k8s_node_labels:
    node.homelab.io/performance: high|mid|low
    node.homelab.io/storage-type: ssd|mmc
    node.homelab.io/storage-tier: fast|standard
    node.homelab.io/arch: arm64
    node.longhorn.io/create-default-disk: 'true'
```

2. **Run k3s installation**:

```bash
make k3s-install
```

Labels will be automatically applied during installation and existing nodes will be updated.

### Verifying Node Labels

Check that labels are correctly applied:

```bash
kubectl get nodes --show-labels
```

View labels for a specific node:

```bash
kubectl describe node <node-name>
```

### Checking Workload Placement

Verify that pods are scheduled on appropriate nodes:

```bash
# Show all pods with their assigned nodes
kubectl get pods -A -o wide

# Check specific namespace
kubectl get pods -n influx -o wide
```

### Troubleshooting

#### Pod stuck in Pending state

If a pod is pending, check if node affinity requirements can be satisfied:

```bash
kubectl describe pod <pod-name> -n <namespace>
```

Look for events indicating node affinity issues. You may need to:

1. Verify node labels are correct
2. Adjust affinity rules in the workload's `values.yaml`
3. Add more nodes with required labels

#### Workload running on unexpected node

Node affinity uses `preferredDuringSchedulingIgnoredDuringExecution`, which means:

- Kubernetes will **try** to place pods on preferred nodes
- If preferred nodes are unavailable/full, pods may run elsewhere
- This ensures availability over strict placement

To force strict placement, change to `requiredDuringSchedulingIgnoredDuringExecution` in the workload's affinity configuration.
