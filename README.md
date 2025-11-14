# Homelab with Kubernetes

## Stability and Troubleshooting

This homelab runs on Raspberry Pi hardware with kube-vip for control plane high availability. The following sections document known stability issues and their resolutions.

### Hardware Requirements

#### Power Supply and Cooling

Raspberry Pi nodes require adequate power and cooling to prevent thermal throttling and stability issues:

- **Power Supply**: Use official Raspberry Pi power supplies (5V/3A minimum)
- **Cooling**: Active cooling (fans/heat sinks) recommended, aim for < 70°C under load
- **Monitoring**: Temperature and throttling metrics are collected via prometheus-rpi-exporter

#### Network Configuration

UniFi network switches require specific configuration for reliable Kubernetes operation:

- **Disable EEE**: Energy Efficient Ethernet must be disabled on all Pi switch ports
- **Link Speed**: Ensure 1000/full duplex operation
- **Port Configuration**: Use standard port settings (no STP modifications due to Sonos compatibility)
- **MTU**: Use 1500 end-to-end (flannel vxlan default)

On Raspberry Pi nodes:

```bash
# EEE is automatically disabled via systemd unit (disable-eth0-eee.service)
sudo systemctl status disable-eth0-eee.service
```

#### Storage

- **SSD Recommended**: Use USB SSD storage for better I/O performance and reliability
- **Health Monitoring**: Monitor for I/O errors in kernel logs
- **Space**: Ensure adequate free space (>10GB) and inodes

### Control Plane High Availability

#### Cilium L2 Configuration

The cluster uses Cilium L2 announcements with the following configuration:

- **L2 Announcements**: Enabled for LoadBalancer service IPs
- **Leader Election**: 15s lease duration, 5s renew deadline, 2s retry period
- **ARP Response**: Nodes respond to ARP requests for virtual IPs
- **Metrics**: Prometheus metrics enabled via Cilium agent

#### Topology Considerations

**Current Setup**: 2 control plane nodes with embedded etcd

**Recommended**: Upgrade to 3 masters for proper etcd quorum and HA

##### Migration Options

**Option 1: Add Third Master (Recommended)**

1. Add third Raspberry Pi to inventory as master
2. Run `make k3s-install` to join as third control plane node
3. etcd will automatically rebalance to 3-node cluster
4. Benefits: Full HA, proper quorum, no SPOF

**Option 2: Single Master + Agents (Temporary)**

1. Convert one master to agent: `k3s server --disable-etcd --server https://VIP:6443`
2. Benefits: Simpler topology, stable single etcd
3. Drawbacks: Control plane SPOF

**Option 3: External etcd (Advanced)**

1. Deploy separate 3-node etcd cluster
2. Configure k3s to use external etcd
3. Benefits: Separates control plane from datastore
4. Drawbacks: Complex, requires additional infrastructure

##### Migration Commands

```bash
# Add third master (recommended)
# 1. Update inventory.yml with third master
# 2. Bootstrap third host
make host-bootstrap

# 3. Install k3s on third master (will auto-join etcd cluster)
make k3s-install

# Verify etcd cluster health
kubectl get nodes
kubectl -n kube-system exec -it etcd-pi-homelab.local -- etcdctl member list
```

### Monitoring and Alerting

#### Metrics Collection

- **prometheus-rpi-exporter**: Raspberry Pi specific metrics (temperature, throttling, voltage)
- **node-exporter**: Standard system metrics
- **blackbox-exporter**: API server VIP availability probing

#### Alerts

Critical alerts configured:

- **KubernetesAPIServerDown**: API VIP unreachable >5 minutes
- **RaspberryPiUnderVoltage**: Power supply issues detected
- **RaspberryPiThrottling**: CPU frequency limiting active
- **RaspberryPiHighTemperature**: >75°C sustained

### Troubleshooting

#### Quick Triage Commands

Run these on control plane nodes during outages:

```bash
# Basic health check
date; uptime; uname -a
k3s -v

# Temperature and power
vcgencmd measure_temp
vcgencmd get_throttled

# Network diagnostics
ip -br a
sudo ethtool -S eth0 | egrep -i 'err|drop|crc|miss'

# Storage health
./scripts/check-storage-health.sh

# k3s service status
sudo journalctl -u k3s -n 100 --no-pager
sudo systemctl status k3s

# Cilium status
cilium status
kubectl get pods -n kube-system -l app=cilium
kubectl get ciliuml2announcementpolicy -A

# Check LoadBalancer services and IP allocation
kubectl get svc -A | grep LoadBalancer
kubectl get ciliumloadbalancerippool -n kube-system
```

#### API Server Unavailable

1. Check Cilium L2 announcement status:

   ```bash
   kubectl get ciliuml2announcementpolicy -n kube-system
   kubectl get svc apiserver-lb -n kube-system
   ```

2. Verify VIP ARP table:

   ```bash
   arp -an | grep 192.168.10.110
   ping -c3 192.168.10.110
   ```

3. Test API endpoints:
   ```bash
   curl -k https://192.168.10.110:6443/readyz
   kubectl get --raw='/readyz?verbose'
   ```

#### High Error Rates on eth0

If `rx_errors` > 1000 or `mdf_err_cnt` > 10000:

1. Verify EEE is disabled:

   ```bash
   sudo ethtool --show-eee eth0
   ```

2. Check UniFi port configuration (EEE disabled, verify link speed)

3. Replace Ethernet cable and test different switch port

#### Thermal/Throttling Issues

If `get_throttled` shows non-zero values:

1. Verify cooling solution and ambient temperature
2. Check power supply quality and cable
3. Monitor with: `vcgencmd get_throttled`

#### Helm Template Issues

If you encounter "undefined variable" errors when deploying monitoring:

```bash
# Test template generation
helm template . --name-template monitoring-system --namespace monitoring-system --dry-run

# If you see "$value" undefined errors, the Prometheus template variables
# in alert annotations need to be properly escaped using: {{ "text" | quote }}
```

#### Raspberry Pi Exporter Issues

If rpi-exporter pods are not running or not collecting metrics:

```bash
# Check pod status
kubectl get pods -n monitoring-system -l app=prometheus-rpi-exporter

# Check pod logs
kubectl logs -n monitoring-system -l app=prometheus-rpi-exporter

# Verify node labels match nodeSelector
kubectl get nodes --show-labels | grep node.homelab.io/arch

# Test direct access to metrics
kubectl port-forward -n monitoring-system svc/prometheus-rpi-exporter 9211:9211
# Then visit: http://localhost:9211/metrics
```

**Common Issues:**

- **Image pull failures**: If you see 401 UNAUTHORIZED, the image registry/tag has changed. Current image: `edgd1er/rpi_exporter:latest`
- **NodeSelector mismatch**: Ensure nodes have `node.homelab.io/arch: arm64` label
- **Missing privileges**: Exporter needs privileged access and `/sys`, `/proc` mounts
- **Hardware access**: Some RPi models may need additional configuration

**Image Registry Changes:**
The original `quay.io/prometheuscommunity/rpi-exporter:v0.3.0` returned 401 UNAUTHORIZED. Using `edgd1er/rpi_exporter:latest` as a working alternative with compatible metrics.

#### Cilium L2 Troubleshooting

When using Cilium L2 announcements for LoadBalancer services and API server VIP:

**L2 Announcement Status:**

```bash
# Check L2 announcement policy
kubectl get ciliuml2announcementpolicy -A

# Check which nodes are announcing IPs
kubectl get ciliuml2announcementpolicy loadbalancer-ips -n kube-system -o yaml
```

**Service IP Allocation:**

```bash
# Check LoadBalancer services
kubectl get svc -A -o wide | grep LoadBalancer

# Check IP pool allocation
kubectl get ciliumloadbalancerippool -n kube-system
kubectl describe ciliumloadbalancerippool homelab-lb-pool -n kube-system
```

**Cilium Status:**

```bash
# Overall Cilium health
cilium status

# Cilium agent logs
kubectl logs -n kube-system -l app=cilium --tail=100
```

**ARP Resolution:**

```bash
# From external machine, check ARP table for VIP
arp -an | grep 192.168.10.110

# Test connectivity to LoadBalancer IP
curl -k https://192.168.10.110:6443
```

**Common L2 Issues:**

- **VIP not reachable**: Check L2 announcement policy nodeSelector matches control plane nodes
- **IP not allocated**: Check CiliumLoadBalancerIPPool range and availability
- **ARP not responding**: Verify l2announcements.enabled: true in Cilium config
- **Interface mismatch**: Check L2 policy interfaces match node network interfaces (eth*, en*)

### Deployment Commands

#### Deploy Monitoring Updates

```bash
# Update monitoring system with new exporters and alerts
helm upgrade --install monitoring-system ./the-lab/system/monitoring-system
```

#### Apply Network and System Updates

```bash
# Apply EEE disable systemd unit and other system optimizations
make host-bootstrap

# Redeploy kube-vip with updated configuration
make k3s-install

# Deploy monitoring updates with Raspberry Pi and API server monitoring
helm upgrade monitoring-system ./the-lab/system/monitoring-system
```

#### UniFi Switch Configuration

In UniFi Controller:

1. Navigate to Settings → Networks → LAN
2. For each Raspberry Pi switch port:
   - Disable "Energy Efficient Ethernet (EEE)"
   - Verify "Speed/Duplex" is set to "Auto" or "1000Mbps/Full-Duplex"
   - Keep default STP settings (do not enable RSTP due to Sonos compatibility)

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

### Control Plane High Availability

The cluster uses Cilium L2 announcements for LoadBalancer services and API server VIP:

- **L2 Announcements**: Nodes respond to ARP requests for LoadBalancer IPs
- **LoadBalancer IPs**: 192.168.10.96-111 range (16 addresses) managed by Cilium LB IPAM
- **API Server VIP**: 192.168.10.110 accessible via L2 announcement
- **Benefits**: Simple single-subnet setup, automatic failover, no router configuration needed

**Deploy with:**

```bash
make k3s-install
```

If a master node fails, traffic automatically fails over within seconds to maintain control plane availability through Cilium's lease-based leader election.

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
