# traefik-tunnel-config-provider

A tiny FastAPI service that turns Kubernetes Gateway API `Gateway` resources into a
[Traefik HTTP provider](https://doc.traefik.io/traefik/providers/http/) config. Traefik
polls the `/api/traefik` endpoint and gets back routers/services that tunnel public traffic
to the gateways you've opted in via annotations.

## How it works

The service watches `gateways` (`gateway.networking.k8s.io/v1`) across all namespaces and,
for each one that opts in, emits Traefik routers pointing at the gateway's assigned IPs.

Opt in with annotations on the `Gateway`:

| Annotation | Effect |
| --- | --- |
| `brodatzki.net/enable-public-tunnel: "true"` | Public router, matches `Host(<listener hostname>)`. |
| `brodatzki.net/add-public-tunnel-rule` | Extra rule `AND`-ed onto the public router. |
| `brodatzki.net/enable-authorized-tunnel: "true"` | Router with the `oidc-ka1` auth middleware (higher priority). |
| `brodatzki.net/add-authorized-tunnel-rule` | Extra rule `AND`-ed onto the authorized router. |

A gateway needs an `HTTPS` listener (for the hostname) and at least one assigned
`IPAddress` in its status, otherwise it's skipped. Routers use the `letsencrypt` cert
resolver. If both tunnels are enabled with identical extra rules, only the authorized one
is kept.

## Endpoints

- `GET /health` — liveness, returns `{"running": true}`.
- `GET /api/traefik` — the Traefik HTTP provider config as YAML.

## Running

In-cluster it uses the mounted ServiceAccount token; locally it falls back to your
kubeconfig (current context). The ServiceAccount needs RBAC to list `gateways`.

```bash
# Local dev
uv run fastapi dev main.py

# Container
docker build -t traefik-tunnel-config-provider .
docker run -p 8000:8000 traefik-tunnel-config-provider
```

Listens on `:8000`.
