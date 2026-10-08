# Deployment modes and threat model

`bitbucket-mcp` can be deployed three ways. They differ in **who holds the Bitbucket
credential** and **who can reach the server** — which is what the security properties
follow from. Pick a mode deliberately: the default (`stdio`) is safe precisely because it
is not reachable from anywhere.

## Matrix

| | **A — stdio (default)** | **B — HTTP, single-tenant** | **C — HTTP, multi-tenant** |
|---|---|---|---|
| Command | `--transport stdio` | `--transport http [--stateless]` | `--transport http --multi-tenant` |
| Credential | `BITBUCKET_TOKEN` (env / keychain) | `BITBUCKET_TOKEN` (env / keychain) | **none on the server** — each request carries the caller's |
| Auth to Bitbucket | Basic (`email:token`) | Basic (`email:token`) | Bearer (caller's OAuth access token, reused as-is) |
| Auth to the MCP server | OS process isolation | **none built in** | OAuth 2.0 bearer, verified per request |
| Who is the actor? | the user who launched the process | the process owner, for every caller | the caller |
| `workspace=None` resolves to | `BITBUCKET_WORKSPACE` | `BITBUCKET_WORKSPACE` | the **caller's** workspace |
| Users per process | 1 | 1 identity, N callers | N identities |
| Audit trail | none (single user) | none (single identity) | `bitbucket_mcp.audit`: tool + `account_id` + workspace |
| Destructive tools | per `configs/tools.json` | per `configs/tools.json` | additionally **off** unless opted in |

## A — stdio, single user

One process per user, spawned by their own MCP client (`uvx`, Claude Code, Codex…). The
credential lives in that user's environment or keychain and never crosses a network.

**Threat model.** The trust boundary is the OS user account. Anyone who can run processes
as that user can already read the token from the environment — the MCP server adds no
exposure. Nothing here changed in v1.25.0.

**Residual risks.** A malicious MCP client, or a prompt-injected agent, acts with the full
rights of the token. Keep the destructive tools disabled in `configs/tools.json` unless you
need them.

## B — HTTP, single-tenant

One process, one Bitbucket identity, reachable over HTTP. Suitable for a *personal* server
on localhost, or a service that legitimately acts under one machine account.

**Threat model.** There is **no authentication on the MCP endpoint**. Every caller who can
reach the port acts with the process token's full rights on the workspace. The security
boundary is entirely the network.

**Requirements.**

- Bind to loopback, or put the port behind a gateway that authenticates callers.
- Set `BITBUCKET_ALLOWED_HOSTS` **and** `BITBUCKET_ALLOWED_ORIGINS` together (DNS-rebinding
  protection). Setting only one rejects every request — they are enforced as a pair.
- Keep destructive tools disabled.
- `--stateless` adds a pagination ceiling (`BITBUCKET_MAX_PAGES_HARD_CAP`, default 10) that
  bounds how much one call can amplify into Bitbucket API traffic.

**Residual risks.** No per-caller attribution: the Bitbucket audit log shows the process
account for every action, whoever triggered it.

## C — HTTP, multi-tenant

```bash
BITBUCKET_RESOURCE_SERVER_URL=https://mcp.example.com \
  python -m src.main --transport http --stateless --multi-tenant
```

Each request carries the caller's own **Bitbucket OAuth access token** as
`Authorization: Bearer`. The server verifies it by use (`GET /2.0/user`), derives the
caller's `account_id` and default workspace, and reuses the same token for the downstream
API calls. **The server stores no credential of its own and maps nothing** — the token
presented *is* the caller's credential, carrying exactly the caller's rights.

Unauthenticated requests get a `401` with a `WWW-Authenticate` challenge pointing at
`/.well-known/oauth-protected-resource`.

**Threat model.**

| Threat | Mitigation |
|---|---|
| One caller acting under another's rights | Per-identity clients, keyed `(account_id, workspace)`. No request ever borrows another's token, and there is no process token to fall back on (fail-closed). |
| Ambient authority via `workspace=None` | The default workspace comes from the *caller's* memberships, never from `BITBUCKET_WORKSPACE`. With zero or several memberships there is no default and the call must name its workspace — it never silently resolves elsewhere. |
| Token leaking into logs / errors / tracebacks | The token is never a dict key (a SHA-256 fingerprint is), never in `repr()` (redacted on the client, the auth strategies, and the access token), and never in an error message. Cache keys and log lines carry `account_id` only. |
| A rotated token still being used | The cached client stores the fingerprint of the token it was built with; a request presenting a different token rebuilds the client instead of reusing the stale credential, and *replaces* the identity's cache entry rather than adding one. |
| Unbounded memory from N identities | The client cache is LRU + TTL bounded (`BITBUCKET_CLIENT_CACHE_SIZE`, default 128; `BITBUCKET_CLIENT_CACHE_TTL`, default 900 s) and closes evicted clients — but only once no in-flight request is using them. |
| Destructive actions by an unvetted caller | Tools flagged `destructiveHint` (merge, decline, `delete_*`, `stop_pipeline`) are refused unless `BITBUCKET_MULTITENANT_ALLOW_DESTRUCTIVE=1`. `BITBUCKET_MULTITENANT_READ_ONLY=1` narrows this further to `readOnlyHint` tools only. |
| No attribution | Every tool call is logged to `bitbucket_mcp.audit` with the tool name, `account_id` and workspace. Never with credentials or arguments. |
| Quota exhaustion across tenants | Bitbucket quotas are **per account**, and each call consumes the *caller's* quota — one tenant cannot drain another's. `BITBUCKET_MAX_PAGES_HARD_CAP` still bounds amplification per call. |

**Residual risks — read these before deploying.**

- **Revocation lag.** A verified token is cached for `BITBUCKET_TOKEN_CACHE_TTL` seconds
  (default 300). A token revoked on Bitbucket's side keeps working until that entry
  expires. Set `BITBUCKET_TOKEN_CACHE_TTL=0` to verify on every request, at the cost of two
  extra Bitbucket calls per request.
- **No server-side scope enforcement.** The server does not inspect scopes; Bitbucket does,
  per call, and a 401/403 surfaces as a typed `AuthorizationError`. A token with broad
  scopes therefore has broad rights — that is by design, since it is the caller's own
  token.
- **Repository and Workspace Access Tokens are not supported.** They are not bound to a
  user account, so `GET /2.0/user` rejects them and no identity can be derived. Use mode B
  for service-to-service automation with those token types.
- **Transport security is still yours.** Bearer tokens in headers require TLS. Terminate
  HTTPS in front of the server, and set the host/origin allowlists.
- **Protocol version.** The Python SDK caps at MCP protocol `2025-11-25`. This mode uses the
  OAuth primitives available there; full alignment with the `2026-07-28` authorization model
  (admin-managed connectors, IdP-group-derived authorization) waits on an SDK that supports
  it.

## Connecting from claude.ai and Claude Code

A multi-tenant deployment can be added to claude.ai as a **custom connector**. An admin adds
it once, and each member clicks *Connect* and signs in through Bitbucket — an Atlassian
login, so the organisation's **SSO** should apply. Claude Code, signed in with the same
claude.ai account, lists the connector and calls its tools.

**How discovery works.** Bitbucket publishes no OAuth authorization-server metadata, so
the server publishes it under its own name:

```
401 WWW-Authenticate  ->  /.well-known/oauth-protected-resource/<path>
                          authorization_servers = [this server's origin]
                      ->  /.well-known/oauth-authorization-server   (served by this server)
                          authorization_endpoint = https://bitbucket.org/site/oauth2/authorize
                          token_endpoint         = https://bitbucket.org/site/oauth2/access_token
```

The client then runs the authorization-code flow **against Bitbucket directly**, holds and
refreshes the tokens, and presents the Bitbucket access token as `Bearer`. The server still
stores nothing. Both well-known documents live at the **root of the origin**: behind a
reverse proxy that mounts the server under a path prefix, route `/.well-known/` to it too.

Leave `BITBUCKET_OAUTH_ISSUER_URL` unset. Pointing it elsewhere turns the route off (`404`);
only do it for an external authorization server that publishes its own metadata. Pointing
it at `https://bitbucket.org`, which publishes none, logs a warning at startup.

**1. Bitbucket OAuth client.** *Workspace settings → Apps and features → OAuth clients →
Create OAuth client*:

- **Authorization**: grant types *Authorization code* and *Refresh token*; callback URL
  `https://claude.ai/api/mcp/auth_callback`.
- **Scopes**: whatever the enabled tools need — *Repositories*, *Pull requests*,
  *Pipelines*, *Issues*… — plus the identity lookups the verifier makes (`/2.0/user`,
  `/2.0/user/workspaces`). The scopes are those of the client: the server requests none.

Bitbucket issues every OAuth client a secret, and its token endpoint refuses an exchange
without it — so the client is confidential by construction.

**2. claude.ai.** *Organization settings → Connectors → Add → Custom*: the MCP endpoint
(e.g. `https://mcp.example.com/mcp`), and under OAuth client **Use your own OAuth client**
with the client ID and secret. The other two options cannot work: Bitbucket publishes no
registration endpoint, and refuses clients that hold no secret.

**3. Claude Code**, signed in with the claude.ai account, lists the connector — nothing to
configure.

**Verified** against Bitbucket Cloud (2026-10-07, real OAuth client with *Account*,
*Workspace membership*, *Repositories* and *Pull requests* read):

- the authorize endpoint accepts `code_challenge` (S256), `resource` and `redirect_uri`;
- the token endpoint accepts `code_verifier` and `resource`, with the secret in the body or
  as Basic auth, and refuses an exchange without the secret;
- refresh works and rotates the refresh token; the access token lasts 2 hours and passes
  the verifier (`/2.0/user`, `/2.0/user/workspaces`);
- the menu path and grant-type options above, as of that date.

**Verified end to end** (2026-10-07, v1.28.0 deployed with the Helm chart behind a Cloudflare
Tunnel): claude.ai discovers the authorization server through this server's metadata — an
issuer whose endpoints live on another host, serialised with a trailing slash — completes
the Bitbucket authorization with *Use your own OAuth client*, and calls tools; Claude Code
inherits the connector; each call is audited under the caller's `account_id`, with the
default workspace resolved from their memberships.

**Not verified yet**: SSO enforcement at the Atlassian login (it depends on the
organisation's Atlassian Guard policy), the minimal scope set, and how many callback URLs a
client accepts.

**Residual risks.**

- **PKCE is advertised, not enforced.** MCP clients refuse an authorization server that
  does not advertise `S256`, so it is advertised. But Bitbucket accepts a wrong
  `code_verifier`: an intercepted authorization code is protected by the **client secret**
  alone.
- **The client secret lives in claude.ai**, in the connector's configuration, where the
  organisation's connector admins manage it. Rotate it in Bitbucket and re-add the
  connector if it leaks.
- **Tokens are not bound to this server.** Bitbucket accepts the `resource` parameter but
  does not scope the token to it, and the server accepts any valid Bitbucket user token it
  can verify by use — including one issued to another application of the same user, and
  vice versa.
- **The client's scopes are a ceiling for every member.** Each member still acts within
  their own Bitbucket permissions, but no member's token can exceed the scopes granted to
  the shared client.

To deploy this mode on Kubernetes — image, Helm chart, per-cluster ingress — see
[deployment-kubernetes.md](deployment-kubernetes.md).

## Configuration reference (multi-tenant)

| Variable | Default | Purpose |
|---|---|---|
| `BITBUCKET_RESOURCE_SERVER_URL` | — (**required**) | This server's public URL; the OAuth resource identifier and metadata base |
| `BITBUCKET_OAUTH_ISSUER_URL` | this server's origin | Advertised authorization server. Unset, this server serves `/.well-known/oauth-authorization-server`, pointing at Bitbucket's endpoints |
| `BITBUCKET_CLIENT_CACHE_SIZE` | `128` | Max cached per-identity clients |
| `BITBUCKET_CLIENT_CACHE_TTL` | `900` | Client cache TTL, seconds; `0` builds a fresh client per request |
| `BITBUCKET_TOKEN_CACHE_SIZE` | `256` | Max cached token verifications |
| `BITBUCKET_TOKEN_CACHE_TTL` | `300` | Verification TTL — **the revocation window**; `0` disables caching |
| `BITBUCKET_MULTITENANT_ALLOW_DESTRUCTIVE` | off | Allow `destructiveHint` tools |
| `BITBUCKET_MULTITENANT_READ_ONLY` | off | Expose `readOnlyHint` tools only |
