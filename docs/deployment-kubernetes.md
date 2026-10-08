# Deploying on Kubernetes

One image and one Helm chart cover every cluster — k3s, an on-premise datacenter, GKE. Both
are generic: what differs per cluster (hostname, TLS, ingress class, network policies) lives
in that cluster's own values file, kept in its infrastructure repository rather than here.

The chart runs **mode C**, multi-tenant HTTP: each caller presents their own Bitbucket OAuth
token and the server holds no Bitbucket credential (see [deployment-modes.md](deployment-modes.md)).
There is no Secret to create.

## Artifacts

Each `v*` release tag publishes, after the version checks and behind the `release`
environment:

| Artifact | Reference |
|---|---|
| Image, `linux/amd64` + `linux/arm64` | `ghcr.io/lawp09/bitbucket-mcp:<version>`, plus `<major>.<minor>` and `latest` |
| Chart (OCI) | `oci://ghcr.io/lawp09/charts/bitbucket-mcp --version <version>`, pinned to the image of the same version |

The image's default command keeps the container idle, for the `docker exec` / stdio usage in
the README; the chart replaces it with the HTTP server
(`--transport http --stateless --multi-tenant`).

`latest` and `<major>.<minor>` follow the last tag pushed: re-running an older release moves them back. Pin `<version>` in production.

**One-time step after the first release**: GHCR creates both packages private. Make
`bitbucket-mcp` and `charts/bitbucket-mcp` public in the repository owner's *Packages*
settings, or give each cluster an image pull secret (`imagePullSecrets`).

## Install

```bash
helm upgrade --install bitbucket-mcp oci://ghcr.io/lawp09/charts/bitbucket-mcp \
  --version <version> -n bitbucket-mcp --create-namespace -f my-values.yaml
```

`publicUrl` is the only required value: the public HTTPS origin, without a path. Everything
else derives from it — the MCP endpoint `<publicUrl>/mcp`, the OAuth resource identifier and
issuer, the Ingress host, and the `BITBUCKET_ALLOWED_HOSTS` / `_ORIGINS` pair. The chart
refuses a `publicUrl` that is not `https://`, carries a path or ends with a slash.

| Value | Default | Purpose |
|---|---|---|
| `publicUrl` | — (required) | Public origin, e.g. `https://mcp.example.com` |
| `extraAllowedHosts` / `extraAllowedOrigins` | `[]` | Other names the server is reached by (an internal hostname) |
| `multiTenant.readOnly` / `.allowDestructive` / `.issuerUrl` | off / off / empty | See the multi-tenant configuration reference |
| `extraEnv` | `[]` | Any other variable (cache sizes, TTLs, page cap); derived variables are refused |
| `ingress.enabled` / `.className` / `.annotations` / `.tls` | off | Standard Ingress over the **whole host** — `/.well-known/` must reach the server too |
| `gke.backendConfig.enabled` | off | GKE only: health check on `/healthz`, backend timeout `timeoutSec` (120) |
| `image.repository` / `image.tag` | `ghcr.io/lawp09/bitbucket-mcp` / the chart's `appVersion` | Pin another image — a fork publishes its own and must point here |

The pod runs as UID 1000 with a read-only root filesystem, no capabilities, no service
account token, and probes on `/healthz` — which, unlike `/mcp`, answers whatever the `Host`
header, so kubelet and load-balancer probes pass the host allowlist.

## Per cluster

Ready-to-adapt values files live in [`charts/bitbucket-mcp/examples/`](../charts/bitbucket-mcp/examples/).

**k3s (Traefik)** — `examples/k3s-traefik.yaml`: `className: traefik`, the `websecure`
entrypoint, a TLS secret in the release namespace. Behind a Cloudflare Tunnel, keep the
public hostname as the `Host` header (do not set `httpHostHeader`), or add the forwarded
name to `extraAllowedHosts`.

**Datacenter (ingress controller with an IngressClass)** — set `ingress.className` to the
controller's class and the TLS secret or certificate annotations it uses (cert-manager:
`cert-manager.io/cluster-issuer`).

**GKE (Ingress for external Application Load Balancer)** — `examples/gke.yaml`:

- GKE ignores `spec.ingressClassName`: leave `className` empty and set the
  `kubernetes.io/ingress.class: gce` annotation (`gce-internal` for an internal LB).
- Enable `gke.backendConfig`: the load balancer health-checks `GET /` by default, which
  answers 404 here and marks the backend unhealthy. The default 30 s backend timeout is
  also short for paginated calls.
- Create the static IP and the certificate outside the chart, then name them in the
  annotations:

  ```bash
  gcloud compute addresses create bitbucket-mcp-ip --global
  kubectl apply -n bitbucket-mcp -f - <<'EOF'
  apiVersion: networking.gke.io/v1
  kind: ManagedCertificate
  metadata:
    name: bitbucket-mcp-cert
  spec:
    domains: [mcp.example.com]
  EOF
  ```

## Network policies

The chart creates none: which peers may reach the pod is cluster-specific. On a cluster
with a default-deny policy, the pod needs ingress from the ingress controller (on GKE, from
the load balancer ranges `130.211.0.0/22` and `35.191.0.0/16`) and egress to DNS and to
`api.bitbucket.org` on 443. A starting point, for a controller in namespace `traefik`:

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: bitbucket-mcp
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: bitbucket-mcp
  policyTypes: [Ingress, Egress]
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: traefik
      ports:
        - port: 8000
  egress:
    - to:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: kube-system
      ports:
        - {port: 53, protocol: UDP}
        - {port: 53, protocol: TCP}
    - ports:
        - {port: 443, protocol: TCP}
```

## Then: claude.ai

Once `curl <publicUrl>/.well-known/oauth-authorization-server` answers from outside the
cluster, add the connector as described in
[deployment-modes.md — Connecting from claude.ai and Claude Code](deployment-modes.md#connecting-from-claudeai-and-claude-code).
