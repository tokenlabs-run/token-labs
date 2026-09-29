# Kubernetes and gateway upgrade record

This is a historical maintenance snapshot from 2026-09-22, including its
unresolved follow-up status. Statements about work in progress below refer to
that snapshot; they do not establish current cluster versions or completion.

Maintenance date: **2026-09-22 UTC**. The Kubernetes 1.35.8 and three-chart
upgrades are complete and serving tests pass. The user subsequently approved
continuing to **Kubernetes 1.37.0**, including dependency upgrades and Envoy's
published support limitation. That follow-up maintenance is **in progress**.

The user explicitly approved node-wide maintenance on `controller`, `spark-01`,
and `spark-02`, including temporary inference, gateway and other service downtime.
This was an approved maintenance operation, **not a zero-downtime upgrade**.
Future production changes must follow the root [operating rules](../../../../AGENTS.md)
and [model rollout runbook](../../../models/MODEL_ROLLOUT_RUNBOOK.md).

## Versions

| Component | Before | After |
| --- | --- | --- |
| Kubernetes API server and all three kubelets | `1.32.13` | `1.35.8` |
| etcd | `3.5.24-0` | `3.6.6-0` |
| CoreDNS | `1.11.3` | `1.13.1` |
| `eg`, namespace `envoy-gateway-system` | `gateway-helm-v1.6.7`, revision 5 | `gateway-helm-1.9.1`, revision 6 |
| `aieg-crd`, namespace `envoy-ai-gateway-system` | `ai-gateway-crds-helm-v0.2.0`, revision 1 | `ai-gateway-crds-helm-1.1.0`, revision 2 |
| `aieg`, namespace `envoy-ai-gateway-system` | `ai-gateway-helm-v0.2.0`, revision 2 | `ai-gateway-helm-1.1.0`, revision 3 |
| Envoy proxy | `1.36.6` | `1.39.1` |
| AI external processor | `0.2.0` | `1.1.0` |

The three chart targets were the latest stable versions returned by the OCI
registry during this maintenance. Kubernetes followed every minor step:
`1.32.13` → `1.33.13` → `1.34.11` → `1.35.8`.

Kubernetes 1.35 was selected within the published ranges for
[Envoy Gateway 1.9](https://gateway.envoyproxy.io/news/releases/matrix/) and
[GPU Operator 25.10](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/25.10/platform-support.html).
The [AI Gateway matrix](https://theagentrouter.ai/docs/compatibility/) lists
Gateway 1.8.1+ for AI Gateway 1.1; it does not by itself establish that this exact
latest combination has passed upstream end-to-end testing. Local serving tests
are therefore recorded separately below. Flannel, Longhorn, GPU drivers and Dynamo were not upgraded.
The later runtime and GPU Operator upgrades are recorded below. In particular, functional storage
checks do not establish a published Longhorn 1.7.3/Kubernetes 1.35 support matrix.

## 1. Inventory and recovery artifacts

Live inspection established a **kubeadm** cluster, not MicroK8s. The only control
plane/etcd node is `controller` (`192.168.1.75`, amd64). Workers `spark-01`
(`192.168.1.76`) and `spark-02` (`192.168.1.77`) are arm64. SSH used worker IP
addresses because their DNS records were stale.

These three Helm releases have no live Flux HelmRelease. Live Flux reconciles
another repository. The stale Envoy pins under `deploy/infrastructure` were
not activated or treated as the installed configuration.

```bash
kubectl config current-context
kubectl get nodes -o wide
kubectl version -o json
helm list -A
kubectl get helmreleases,kustomizations,gitrepositories -A

helm show chart oci://docker.io/envoyproxy/gateway-helm
helm show chart oci://docker.io/envoyproxy/ai-gateway-crds-helm
helm show chart oci://docker.io/envoyproxy/ai-gateway-helm
```

Recovery artifacts are private on `controller` at
`/tmp/tokenlabs-maintenance-20260922.WiIsc3`, mode 700. They include:

- Verified etcd snapshots before maintenance, 1.34 and 1.35.
- Controller/worker configuration backups, including Kubernetes certificates.
- Original Helm values, manifests and history; CRDs with managed fields.
- Original workloads, Dynamo replica counts, storage state, Service selectors
  and endpoints; exact Dynamo restoration patches.
- Pinned chart artifacts, rendered manifests, upgrade logs and validation output.

Do not commit raw exports: they can contain credentials. Backups in `/tmp`
need retention outside temporary-file cleanup for long-term recovery. Snapshot
integrity was checked; a full disaster-recovery restore was not rehearsed.

The following pattern created the fresh snapshot before 1.35:

```bash
kubectl exec -n kube-system etcd-controller -- etcdctl \
  --endpoints=https://127.0.0.1:2379 \
  --cacert=/etc/kubernetes/pki/etcd/ca.crt \
  --cert=/etc/kubernetes/pki/etcd/healthcheck-client.crt \
  --key=/etc/kubernetes/pki/etcd/healthcheck-client.key \
  snapshot save /var/lib/etcd/tokenlabs-before-1.35.db
kubectl exec -n kube-system etcd-controller -- etcdutl snapshot status \
  /var/lib/etcd/tokenlabs-before-1.35.db --write-out=table
```

That snapshot was copied with root-only permissions into the private artifact
directory. Its hash was `1aa91b04`, revision `100380496`, with 9,156 keys.

## 2. Prepare the maintenance window

There was no spare GPU capacity for an independent replacement inference path.
The initial Dynamo-only approval was insufficient for node-wide drains; those
drains proceeded only after the user explicitly approved broader maintenance.
Dynamo was restored and public inference tested while awaiting that approval.

During the approved window:

1. Saved the active `qwen3-30b-control-dynamo-disagg` resource and exact replica
   restoration patch. Scaled its frontend, prefill and decode components from
   one to zero through the owning DynamoGraphDeployment. Inactive Dynamo graphs
   remained at zero. Model configuration and cached weights were preserved.
2. Scaled `dynamo-system/dynamo-platform-nats` and `monitoring/tempo`
   StatefulSets from one to zero after checking PVC retention.
3. Temporarily changed Longhorn `node-drain-policy` from
   `block-if-contains-last-replica` to `allow-if-replica-is-stopped`.
   Confirmed all six Longhorn volumes detached before worker drains.
4. Used normal eviction and respected disruption budgets. No persistent volume
   was deleted, no node was removed, and no forced eviction bypass was used.

## 3. Upgrade Kubernetes one minor at a time

**`sudo kubeadm upgrade apply <version> --yes` is the control-plane upgrade
command.** It does not install matching kubelet binaries on every node.
`kubectl get nodes` reports kubelet versions; an older version there after
`upgrade apply` means the node package/restart work remains.

For each target (`1.33.13`, `1.34.11`, `1.35.8`), the exact kubeadm package was
installed on all nodes, the plan was inspected, and the controller was upgraded.
Then controller, spark-01 and spark-02 were drained and upgraded sequentially.
All nodes reached Ready at the target version before the next minor began.

These are the commands used, parameterized for the final minor step:

```bash
# On each node, retaining its existing signing-key configuration:
TARGET=1.35.8
PREVIOUS_MINOR=1.34
TARGET_MINOR=${TARGET%.*}
sudo cp /etc/apt/sources.list.d/kubernetes.list "/tmp/kubernetes-repo-before-${TARGET}.list"
sudo sed -i "s#stable:/v${PREVIOUS_MINOR}/deb/#stable:/v${TARGET_MINOR}/deb/#" /etc/apt/sources.list.d/kubernetes.list
sudo apt-get update -o Dir::Etc::sourcelist=sources.list.d/kubernetes.list -o Dir::Etc::sourceparts=- -o APT::Get::List-Cleanup=0
sudo env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l apt-get install -y --allow-change-held-packages "kubeadm=${TARGET}-1.1"
sudo apt-mark hold kubeadm
sudo env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l apt-get install -y --download-only --allow-change-held-packages "kubelet=${TARGET}-1.1" "kubectl=${TARGET}-1.1"

# Controller only: review the plan before applying it.
sudo kubeadm upgrade plan "v$TARGET"
sudo kubeadm upgrade apply "v$TARGET" --yes

# On each worker, before that worker's kubelet upgrade:
sudo kubeadm upgrade node

# From the administration host, one node at a time:
NODE=controller  # then spark-01, then spark-02
kubectl drain "$NODE" --ignore-daemonsets --delete-emptydir-data --timeout=300s

# On that drained node:
sudo env DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l apt-get install -y --allow-change-held-packages "kubelet=${TARGET}-1.1" "kubectl=${TARGET}-1.1"
sudo apt-mark hold kubeadm kubelet kubectl
sudo systemctl daemon-reload
sudo systemctl restart kubelet

# From the administration host:
kubectl uncordon "$NODE"
kubectl wait --for=condition=Ready "node/$NODE" --timeout=180s
kubectl get node "$NODE" -o jsonpath='{.status.nodeInfo.kubeletVersion}{"\n"}'
```

Readiness can briefly reflect the preceding kubelet; the execution helper
required both Ready and the exact target version. All nodes were uncordoned and
package holds restored. The sole API server was temporarily unavailable during
static-pod restarts. Kubeadm completed each upgrade successfully, including etcd
3.6.5 at Kubernetes 1.34 and etcd 3.6.6 at Kubernetes 1.35.

## 4. Compare values and migrate CRDs

Exported the installed overrides and compared them with target chart defaults:

```bash
umask 077
ARTIFACTS=/tmp/tokenlabs-maintenance-20260922.WiIsc3
helm get values eg -n envoy-gateway-system -o yaml > "$ARTIFACTS/eg-values.yaml"
helm show values oci://docker.io/envoyproxy/gateway-helm --version 1.9.1 > "$ARTIFACTS/eg-target-defaults.yaml"
diff -u "$ARTIFACTS/eg-values.yaml" "$ARTIFACTS/eg-target-defaults.yaml"

helm get values aieg -n envoy-ai-gateway-system -o yaml > "$ARTIFACTS/aieg-values.yaml"
helm show values oci://docker.io/envoyproxy/ai-gateway-helm --version 1.1.0 > "$ARTIFACTS/aieg-target-defaults.yaml"
diff -u "$ARTIFACTS/aieg-values.yaml" "$ARTIFACTS/aieg-target-defaults.yaml"

helm get values aieg-crd -n envoy-ai-gateway-system -o yaml > "$ARTIFACTS/aieg-crd-values.yaml"
helm show values oci://docker.io/envoyproxy/ai-gateway-crds-helm --version 1.1.0 > "$ARTIFACTS/aieg-crd-target-defaults.yaml"
diff -u "$ARTIFACTS/aieg-crd-values.yaml" "$ARTIFACTS/aieg-crd-target-defaults.yaml"
```

These exports were taken **before** upgrading; rerunning them now exports the
new releases. `diff` exits 1 for differences. Overrides are a subset of defaults,
so a large diff is expected. Checked schema/migration changes and rendered
resources instead of assuming every absent default key was invalid.

The credential-free reviewed overrides are checked in as
[envoy-gateway.yaml](values/envoy-gateway.yaml) and
[ai-gateway.yaml](values/ai-gateway.yaml). They preserve controller pinning and
tolerations. Envoy values include AI 1.1's
[required extension hooks](https://github.com/envoyproxy/ai-gateway/blob/v1.1.0/manifests/envoy-gateway-values.yaml)
and disable bundled CRDs because those are managed separately. Did not use
`--reuse-values`.

The reported server-side conflict involved fields previously owned by `helm`.
The existing Gateway API channel was **experimental**. Rendered the same channel
at 1.9.1, reviewed ownership and schemas, and verified every existing stored
version remains in the target CRDs. AI CRDs retain served `v1alpha1` while adding
`v1beta1` as storage. No CRD deletion or editing of `status.storedVersions` occurred.

```bash
helm template eg-crds oci://docker.io/envoyproxy/gateway-crds-helm \
  --version 1.9.1 \
  --set crds.gatewayAPI.enabled=true \
  --set crds.gatewayAPI.channel=experimental \
  --set crds.envoyGateway.enabled=true > "$ARTIFACTS/eg-crds-target.yaml"
kubectl apply --server-side --dry-run=server \
  --field-manager=tokenlabs-gateway-upgrade --force-conflicts \
  -f "$ARTIFACTS/eg-crds-target.yaml"
```

`--force-conflicts` was used for this reviewed ownership transition after backup
and successful server dry-run. It is not a general fix for unexplained conflicts.
Gateway API CRDs are now 1.6.1 experimental; Gateway/Envoy CRDs and the safe-upgrade
admission policy are managed with field manager `tokenlabs-gateway-upgrade`.
AI CRDs remain owned by their existing Helm release `aieg-crd`.

## 5. Upgrade the three charts and migrate the route

Pinned charts were pulled into `$ARTIFACTS/charts` and rendered before mutation.
The actual commands used those local chart artifacts. From the repository root:

```bash
# Downloaded and reviewed before the maintenance mutation:
helm pull oci://docker.io/envoyproxy/gateway-helm --version 1.9.1 --untar --untardir "$ARTIFACTS/charts"
helm pull oci://docker.io/envoyproxy/ai-gateway-crds-helm --version 1.1.0 --untar --untardir "$ARTIFACTS/charts"
helm pull oci://docker.io/envoyproxy/ai-gateway-helm --version 1.1.0 --untar --untardir "$ARTIFACTS/charts"

# Stop the old reconcilers during this approved maintenance migration.
kubectl scale deployment/envoy-gateway -n envoy-gateway-system --replicas=0
kubectl scale deployment/ai-gateway-controller -n envoy-ai-gateway-system --replicas=0
kubectl rollout status deployment/envoy-gateway -n envoy-gateway-system --timeout=120s
kubectl rollout status deployment/ai-gateway-controller -n envoy-ai-gateway-system --timeout=120s

kubectl apply --server-side --field-manager=tokenlabs-gateway-upgrade \
  --force-conflicts -f "$ARTIFACTS/eg-crds-target.yaml"
helm upgrade aieg-crd "$ARTIFACTS/charts/ai-gateway-crds-helm" \
  -n envoy-ai-gateway-system --reset-values --wait --timeout=5m

kubectl apply --dry-run=server -f deploy/platform/gateway/aigatewayroute-models.yaml
kubectl apply -f deploy/platform/gateway/aigatewayroute-models.yaml

helm upgrade aieg "$ARTIFACTS/charts/ai-gateway-helm" \
  -n envoy-ai-gateway-system --reset-values \
  -f deploy/platform/gateway/upgrades/values/ai-gateway.yaml --wait --timeout=10m
helm upgrade eg "$ARTIFACTS/charts/gateway-helm" \
  -n envoy-gateway-system --reset-values \
  -f deploy/platform/gateway/upgrades/values/envoy-gateway.yaml --wait --timeout=10m
kubectl rollout status deployment/envoy-token-labs-token-labs-gateway-bd0838a6 \
  -n envoy-gateway-system --timeout=300s
```

Both Helm controller upgrades restored their original one replica. The route
migration updated the generator and generated file to `v1beta1`, replaced
`AIGatewayRoute.spec.targetRefs` with `parentRefs`, and removed route-level
`schema`. `AIServiceBackend.spec.schema` remains. Preserved the model inventory,
backend hostname and existing route identity; did not regenerate an empty route
from the temporarily stopped workloads.

The target AI sidecar is a native sidecar: inspect `spec.initContainers` and
`status.initContainerStatuses`, not only `spec.containers`. The generated proxy
uses Envoy 1.39.1, gateway shutdown-manager 1.9.1, and AI extproc 1.1.0. Allowed
old proxy pods to drain normally without force-deleting them. The legacy 0.2 streaming policy initially remained, but the final serving test
revealed duplicate AI filters. It was removed as described below; the model
catalog route retains its separate policy override.

Verified OCI chart digests:

| Chart | SHA256 |
| --- | --- |
| gateway-helm 1.9.1 | `5b99aa5c1d73d21cd0356e931bd9979ada026dd6b7d1037fbfc3c94cbffef3c3` |
| ai-gateway-crds-helm 1.1.0 | `2d12db64ec84179d23385cbbb3e47fbe6860bbb934cc55b82f33fc7cab25f4ce` |
| ai-gateway-helm 1.1.0 | `d599481cc8259a7d353207f140f16e40c31a39fca934e83013c89a6f5793269e` |

## 6. Restore and validate

After the final node upgrade, restored the Longhorn drain policy and both
StatefulSet replica counts. After the charts upgraded and NATS was ready,
restored the original active Dynamo graph. Inactive graphs remain stopped.

```bash
kubectl patch settings.longhorn.io node-drain-policy -n longhorn-system \
  --type=merge -p '{"value":"block-if-contains-last-replica"}'
kubectl scale statefulset/dynamo-platform-nats -n dynamo-system --replicas=1
kubectl scale statefulset/tempo -n monitoring --replicas=1
kubectl rollout status statefulset/dynamo-platform-nats -n dynamo-system --timeout=180s
kubectl patch dynamographdeployment qwen3-30b-control-dynamo-disagg -n token-labs \
  --type=json --patch-file "$ARTIFACTS/dynamo-restore-patch.json"

kubectl get nodes -o wide
kubectl version -o json
kubectl get --raw=/readyz
helm list -n envoy-gateway-system
helm list -n envoy-ai-gateway-system
kubectl get pods -n token-labs -o wide
```

Validation after the first maintenance window:

- All three nodes Ready and schedulable on `v1.35.8`; API and etcd healthy.
- Both Spark GPUs allocatable; Dynamo/Grove/KAI and storage controllers ready.
- All three Helm releases `deployed` at the target versions; AI route Accepted.
- New proxy and native AI sidecar ready on controller. Production Service UID,
  selector, ClusterIP, ports (including NodePort `31426`) and
  `externalTrafficPolicy: Local` are unchanged; a ready endpoint exists.
- NATS ready with its original persistent volume attached and healthy.
- Seven route-generator unit tests passed; README shell syntax and links checked.
- Public `/v1/models` returned HTTP 200 with the expected model after warm-up.
- Direct model warm-up returned HTTP 200 and `OK` (20.315 seconds).
- Public non-streaming chat returned HTTP 200 and `OK` (0.553 seconds).
- Short streaming returned HTTP 200 with four SSE events and `[DONE]` (0.588 seconds).
- The initial 768-token streaming probe exposed a duplicate-filter regression;
  the correction and successful retest are recorded below.

### Streaming regression found and fixed

A 768-token SSE probe initially returned HTTP 500 with
`response_payload_too_large`. A private Envoy configuration dump showed both
`envoy.filters.http.ext_proc/aigateway` (the new native filter) and the legacy
`ai-eg-eep-token-labs-gateway` filter enabled on the same chat routes. Backed up
the legacy policy to `legacy-ai-eep-before-removal.yaml`.

Automatic approval review initially rejected the deletion; the user then
explicitly said to proceed. Removed the duplicate policy and its obsolete
checked-in `extproc-streaming-policy.yaml` to prevent reapplication:

```bash
kubectl delete envoyextensionpolicy ai-eg-eep-token-labs-gateway -n token-labs --wait=true
```

Retesting passed: model catalog HTTP 200, non-streaming chat HTTP 200 with `OK`
in 0.498 seconds, and a 768-token SSE response with 769 events and `[DONE]`.
First streamed content arrived at 0.447 seconds; the complete stream took
14.269 seconds. These are smoke-test observations, not a load benchmark.


Tempo was unready before maintenance. Its restored pod remains blocked by
filesystem errors on PVC `pvc-6de4dfe3-0b00-407b-a804-918993fcf125`; automatic fsck
cannot repair it. No filesystem repair or data deletion was attempted. The
`ai-trading` Deployment also had zero ready replicas before maintenance; compare
final workload readiness against the captured baseline.

## Rolling updates and recovery limits

The gateway Deployments use `RollingUpdate`, but Helm completion alone does not
prove uninterrupted serving. This operation intentionally stopped workloads and
reconcilers under the approved maintenance exception. It was not a blue/green
promotion and provides no zero-downtime claim or load/capacity certification.

Retain backups and Helm history. `helm rollback` does not roll back Kubernetes,
etcd or CRD storage. Do not delete or blindly downgrade CRDs, clear stored-version
status, or assume old controllers can consume the migrated route schema. Any
recovery must account for the coordinated CRD, route and controller versions.

## Requested follow-up: Kubernetes 1.37.0

The user subsequently requested `v1.37.0`. Official release endpoints confirm
it is stable, with `v1.36.4` as the intermediate minor target. **All nodes completed 1.36.4; the 1.37.0 control-plane upgrade is running.** The user approved proceeding despite the stable Envoy support gap. Streaming
was repaired first. Runtime 2.3.5 and GPU Operator 26.7.0 prerequisites are complete
before the Kubernetes 1.36.4 → 1.37.0 sequence.

Dependency review before the 1.37 follow-up:

- [Envoy Gateway's matrix](https://gateway.envoyproxy.io/news/releases/matrix/)
  lists stable 1.9 with Kubernetes 1.33–1.36. Its development `latest` row
  includes 1.37; that is not a stable production chart recommendation.
- GPU Operator started at `25.10.1`, managed by Flux's
  `flux-system/gpu-operator` HelmRelease. Its version-specific matrix covers
  Kubernetes through 1.35. The current
  [GPU Operator matrix](https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/platform-support.html)
  lists 26.7 with Kubernetes 1.37 and marks 25.10 end-of-support. Supported
  operator upgrades proceed one major at a time, requiring review of 26.3 and
  26.7. Host drivers/toolkit are preinstalled (`driver.enabled=false`,
  `toolkit.enabled=false`); do not accidentally enable operator-managed drivers.
- [containerd's recommended matrix](https://containerd.io/releases/) lists
  2.3+ for Kubernetes 1.37. Initial runtime versions were 2.2.1 on controller
  and 1.7.28 on workers. The
  [Kubernetes runtime documentation](https://kubernetes.io/docs/setup/production-environment/container-runtimes/)
  still describes the 1.x cgroup-driver fallback in 1.37, with removal in 1.38;
  the recommendation matrix must not be misreported as an unconditional 1.36
  runtime hard failure.

A further upgrade requires resolving these dependencies and the stable Envoy
support gap, taking fresh backups, then repeating the one-minor-at-a-time node
sequence. The previous successful 1.35 tests do not validate 1.37.

### Follow-up preparation and runtime migration

- Captured a fresh etcd snapshot after successful gateway/inference validation:
  `etcd-before-1.37-work.db`, hash `b314fb24`, revision `100419966`.
- Resolved GPU Operator targets `26.3.3` and `26.7.0`; both rendered with host
  driver and toolkit installation still disabled. Prepared an isolated worktree
  of `elizabetht/homelab` from `origin/main` for authoritative Flux changes.
- Downloaded containerd **2.3.5** packages from Docker's signed Ubuntu repository
  for amd64/arm64. Verified the signing-key fingerprint and restricted the new
  apt source to containerd. Package simulation revealed Docker package removal
  on the controller, so packages were **downloaded and extracted, not installed**.
- Runtime binaries are staged in `/opt/tokenlabs/containerd/2.3.5/usr/bin`.
  Configuration backups are root-only under
  `/var/backups/tokenlabs-k8s-137-20260922` on each node. Migrated configuration
  to the schema emitted by 2.3.5 (version 4), flattened legacy imports, and checked
  root/state paths, runtime names, NVIDIA BinaryName and SystemdCgroup. A controller
  import that would have changed its runtime from runc to nvidia was excluded.
- Activation uses `/etc/systemd/system/containerd.service.d/20-tokenlabs-runtime.conf`
  to select the pinned binary and matching shim/runc PATH. Existing Ubuntu/Docker
  packages are retained; their package version is not the active runtime version.
  Future runtime updates must deliberately update this override and pinned path.
  This runtime is managed by this maintenance procedure, not automatic apt updates.
- Paused Dynamo and retained-volume StatefulSets again, using the same documented
  Longhorn maintenance policy. Runtime activation is sequential after each drain.
  Validate CRI readiness and a real GPU container on each Spark before proceeding.

Runtime activation completed on all three nodes; the API reports
`containerd://2.3.5`. Both workers passed an actual `nvidia-smi -L` GPU pod test.
Spark-02 first exposed a device-registration timing race and then an explicit
CDI-disabled error. Enabled `plugins."io.containerd.cri.v1.runtime".enable_cdi`
on that worker, restarted containerd, and the test passed. The controller's two
existing Docker containers remained running. Direct 1.7 LTS → 2.3 LTS runtime
upgrades are supported by the [containerd upgrade policy](https://containerd.io/releases/).

The intermediate GPU Operator GitOps change is a verified GitHub-signed commit:
[b27cc14](https://github.com/elizabetht/homelab/commit/b27cc149564247614c3b5fbb17e3a544b43ef6b8).
Local interactive GPG signing was unavailable; an unsigned commit was rejected by
automatic approval review. Used GitHub's `createCommitOnBranch` signing API instead
and verified the signature. No signing setting was disabled. Flux reconciliation
uses the existing HelmRelease owner:

```bash
flux reconcile source git flux-system -n flux-system --timeout=2m
flux reconcile kustomization infrastructure -n flux-system --timeout=3m
flux reconcile helmrelease gpu-operator -n flux-system --with-source --timeout=10m
kubectl wait --for=jsonpath='{.status.state}'=ready clusterpolicy/cluster-policy --timeout=300s
```

### GPU Operator follow-up

The intermediate 26.3.3 upgrade exceeded Flux's original five-minute timeout
while downloading DCGM images and waiting for exporter readiness. Its automatic
rollback to 25.10.1 failed because the upgraded CRD rejected a null
`spec.migManager.config.name`. Flux subsequently recovered forward to 26.3.3;
the HelmRelease, ClusterPolicy, and all GPU daemonsets were verified ready.
No CRD validation was weakened and no GPU resource was deleted to bypass it.

The final 26.7.0 change is signed commit
[736b750](https://github.com/elizabetht/homelab/commit/736b7509c2f9ebacc37af8715662d046c41a752e).
It sets `spec.timeout: 15m` and the supported Flux upgrade strategy
`RetryOnFailure` with `retryInterval: 2m`. This allows readiness time and retries
forward instead of attempting an incompatible old-chart rollback after CRD
migration. Host driver/toolkit installation remains disabled.

### Kubernetes 1.36 / 1.37 execution

Before the 1.36 control-plane change, captured and checked
`etcd-before-1.36.db`: hash `b206a3df`, revision `100441237`, 6,874 keys.
The Kubernetes 1.36.4 plan required no manual component configuration changes.
Preloaded images with:

```bash
sudo kubeadm config images pull --kubernetes-version v1.36.4
```

The same package/drain sequence in section 3 applies to both additional steps:
first `PREVIOUS_MINOR=1.35`, `TARGET=1.36.4`; then `PREVIOUS_MINOR=1.36`,
`TARGET=1.37.0`. Each `kubeadm upgrade apply` is followed by kubelet/kubectl
installation and verification on controller, spark-01, then spark-02.

GPU Operator 26.7.0 reached HelmRelease Ready and ClusterPolicy `ready`; every
GPU daemonset reached its desired ready count. Flux infrastructure applied
revision `736b7509c2f9ebacc37af8715662d046c41a752e` successfully.

During the 1.36 controller drain, Flux's Helm controller retained its configured
600-second termination grace period while outstanding chart downloads retried
against the drained source-controller. The drain waited for normal shutdown;
this explains a pause after the API-server upgrade succeeded. Do not infer a
stalled Kubernetes upgrade from that delay or force-delete the controller.

All three nodes completed 1.36.4 and returned Ready/schedulable. CoreDNS,
Flannel, kube-proxy, GPU ClusterPolicy and storage controllers were healthy.
A fresh `etcd-before-1.37.db` snapshot passed verification: hash `6d648c8e`,
revision `100451681`, 8,421 keys, 202 MB. Kubeadm 1.37.0 was installed on all
nodes and matching kubelet/kubectl packages downloaded before the final plan.

The 1.37.0 plan passed health/preflight checks without manual config migration.
It targets etcd `3.7.0-0` and CoreDNS `1.14.6`; execution uses
`sudo kubeadm upgrade apply v1.37.0 --yes`.
