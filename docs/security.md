# Security

An agent is driven by a language model, and its instructions and tools are often configured by makers
outside IT. Treat it as a client you can't fully trust: it can be steered by a prompt, by a document it
reads, or by data a tool returns. Every control on this page assumes the agent will eventually attempt
something it shouldn't, and puts the refusal somewhere the agent can't influence.

This page is the source of truth for each control's status; the evidence behind each status is in
[testing.md](testing.md).

| Mark | Meaning |
|---|---|
| ✅ | Built, and tested here. The row names the test |
| 🔲 | Built or configured, not tested here |
| ⏳ | Not built |

The network controls apply to the **secure profile**. The rapid profile, for development, has public
endpoints and none of them; identity, allow-lists, validation, rate limits and logging are the same in
both ([architecture.md](architecture.md#the-two-deployment-profiles)).

## Threat model

What the design defends against, and where the defence sits:

| Threat | Example | Defence | Status |
|---|---|---|---|
| **The agent calls a tool it wasn't given** | The model is talked into reading finance data through an agent meant for general questions | The tool isn't listed by the MCP servers that agent uses, and the API policy's allow-list refuses the operation | ✅ |
| **A valid token is used somewhere else** | One agent's token is presented to an MCP server that agent doesn't use, or to the REST API directly, or to the backend API directly | The MCP server policy (401), the API policy on every path (403), and the network (dropped) | ✅ |
| **Someone signs in as an agent** | A user obtains a token carrying an agent's client app ID and acts as that agent | Agents' client apps accept no public-client sign-in; the connector authenticates with a managed identity, so there is no secret to steal | ✅ |
| **The agent reads data the user may not see** | A user without finance access asks the Finance Assistant for spending | Delegated access: the database receives the user's identity and refuses | ✅ |
| **The backend API's own identity is used to get around user permissions** | An app-only tool returns data to anyone | An app role checked at the gateway, a narrow tool, and a database identity that can read one view | ✅ |
| **The model writes its own query** | "Run `DROP TABLE`", or a crafted filter | Tools take typed parameters; the gateway validates them; the backend API runs one fixed, parameterised statement | ✅ |
| **A manipulated agent changes data** | The model is steered into setting a forecast to a wrong value | The user's own database permission (only Budget Editors can write), bounded parameters, and the writer recorded by the database. No approval gate and no change history | 🔲 Gated by permission only ([ai-safety.md](ai-safety.md#the-write-tool-as-built)) |
| **A runaway or abusive agent floods a system** | A loop, or bulk extraction | A rate limit per agent and user | ✅ |
| **A tool result steers the model** (indirect prompt injection) | A database row containing instructions | Limits the damage, doesn't prevent it: the agent can still only call its own tools, as the user. See [ai-safety.md](ai-safety.md) | ✅ Two crafted tool results were ignored in Preview ([probe 1](ai-safety.md#probes)); weak evidence |
| **A maker attaches another agent's connector** | The borrowed connector brings that agent's tools | Not prevented by the gateway: the connector *is* the agent's identity. Restrict who can use each connector | ⏳ Confirmed as a gap |
| **A maker adds an uncontrolled tool or knowledge source** | A third-party MCP server, or a public website | The environment's data policy, an allow-list ([governance.md](governance.md)) | ✅ |
| **Secrets leak** | A client secret in a repository or a connector | There are none: managed identities with federated identity credentials throughout | ✅ |
| **Payloads leak through logs** | Tool results in telemetry | Request and response bodies aren't logged; Copilot Studio sensitive properties are off. **Tool arguments may still be logged** if they travel in the query string and the gateway log records the URL; on the rapid profile no gateway row held a query string. Conversation transcripts hold tool results | ✅ bodies / ⏳ arguments and transcripts ([observability.md](observability.md#what-is-recorded-and-what-is-not)) |

Not in scope: denial of service against the gateway itself, a compromised administrator, and supply
chain attacks on the platform services.

## The five rules that matter most

### 1. Authorise at the API, not only at the MCP server

API Management exposes each REST API twice: as an **MCP server** for each agent's client app
(`/<agent>-mcp/mcp`) and as the plain **REST API** it was imported from (`/tools/...`). Checking the
agent at the MCP server alone is not enough: anyone holding a valid token can skip it and call
`/tools/<operation>` directly.

![One REST API exposed through two front doors: domain MCP servers and the plain REST API. The Employee Assistant's call through the directory server is allowed; its token is refused at the finance server (401), at the REST API's policy when calling an operation the Employee Assistant isn't allowed (403), and by the network when calling the backend API directly.](diagrams/rest-api-two-front-doors.svg)

<details>
<summary>Diagram description</summary>

Inside Azure API Management, one REST API is exposed through two front doors. Front door 1 is a set
of MCP servers, one for each agent's client app, each with a policy that accepts only that app's
tokens. Front door 2 is the REST API itself at `/tools/*`, whose policy runs on every path: it
validates the token, checks an allow-list of operation and agent pairs, and denies anything not listed.
Below the policy are the operations: GET /directory/me, GET /finance/cost-centres, GET /finance/spend,
and GET /diagnostics/caller (not a tool). To the right, the backend API sits behind a private endpoint,
with a network security group admitting only API Management. Path 1 (allowed): the Employee Assistant
calls the directory server, the tool maps to GET /directory/me, and the request reaches the backend API
through the private endpoint. Path 2 (refused, 401): the Employee Assistant's token at the Finance
Assistant's MCP server. Path 3 (refused, 403): a client with the Employee Assistant's token calls GET
/tools/finance/spend directly; the API policy refuses it because `finance_query_spend` isn't on the
Employee Assistant's list. Path 4 (dropped): the same client calls the backend API directly; the
network security group drops it because it doesn't come from API Management.
</details>

| Path | What happens | Enforced by | Evidence |
|---|---|---|---|
| 1 | The Employee Assistant calls `directory_get_my_profile` through the directory server | Allowed | ✅ Smoke test check 1; the call itself is in the pressure test's grid |
| 2 | The Employee Assistant's token at the finance server | **401**, MCP server policy | ✅ Smoke test check 3; also with a real agent |
| 3 | The Employee Assistant's token on `/tools/finance/spend`, skipping the MCP server | **403**, API policy allow-list | ✅ Smoke test check 7 |
| 4 | The Employee Assistant's token straight to the backend API | **Dropped**, network security group on the private endpoint subnet | ✅ Smoke test check 8 (secure profile) |

**This bypass was found by testing, not by review.** Before the API policy existed, an agent whose only
tool read its own sign-in token used the REST API to read Microsoft Graph and Azure SQL data, and got
HTTP 200. The fix is a policy on the REST API itself
([api-policy.xml.tftpl](../infra/modules/contoso-gateway/policies/api-policy.xml.tftpl)) that runs on
**every** path in, MCP or direct:

- validate the token (tenant, audience, the `Tools.Read` scope, a known agent's client app);
- allow the call only if the pair `<operation>|<client app ID>` is on the allow-list;
- deny everything else, including operations no agent lists.

The allow-list and the MCP servers' tool lists are generated from one map (`server_definitions` and
`agent_definitions` in the module's [main.tf](../infra/modules/contoso-gateway/main.tf)), so they can't
drift apart.

#### Four questions, four layers

A tool is defined once and can be shared by any number of agents, or restricted to one.

![Two agents and two domain MCP servers. The directory server lists directory_get_my_profile and is used by both agents; the finance server lists the finance and budgeting tools and is used by the Finance Assistant only. Tools map to finance and budgeting REST imports; Graph and two SQL databases sit behind the backends. One map generates MCP servers and the allow-list.](diagrams/agent-tool-access.svg)

<details>
<summary>Diagram description</summary>

Four column headings: Which agent? (its own client app, accepted by the servers it uses), Which tools?
(the servers list the agent's approved tools), Which operation? (the API policy's allow-list, checked on every
path) and Which data? (the system applies the user's permissions, or the gateway's role check for
the app-only tool). The Employee Assistant connects to the directory server, which lists directory_get_my_profile. The
Finance Assistant connects to the directory server and to the finance server, which lists
finance_list_cost_centres, finance_query_spend, budgeting_get_forecast and budgeting_update_…. Lines
join each tool to an operation of the Contoso REST APIs (finance + budgeting imports): the directory
server is used by both agents; finance and budgeting operations are on the finance server, used by the
Finance Assistant only. Backends call Microsoft Graph and the finance database as the
user (or app-only for cost centres), and the budgeting database as a second Contoso system. A
configuration box shows the server and agent maps, which generate both the MCP servers and the allow-list.
</details>

| Question | Answered by | Changed by |
|---|---|---|
| **Which agent** is calling? | The token's `azp` claim (the agent's client app), checked by each server's policy and by the API policy | Adding an agent to `agent_definitions` |
| **Which tools** can it see? | The MCP servers an agent uses list only its approved tools | Editing the agent's `servers` list, or a server's `tools` |
| **Which operation** may it call? | The API policy's allow-list of operation and agent pairs, on every path | Generated from the same two maps |
| **Which data** comes back? | For delegated tools, the source system, because the backend API calls it as the user. For app-only tools, an app role checked at the gateway | The user's own permissions, or the role assignment |

The first three layers restrict the **agent**; the fourth restricts the **user**. An agent granted
`finance_query_spend` still can't read anything the signed-in user couldn't read themselves: the
database refuses anyone outside Contoso Finance Readers.

### 2. The backend accepts traffic from the gateway only

App Service authentication on the backend API checks that a token is *for this API*. It doesn't check
*which agent* may use *which route*. So if agents can reach the backend API directly, every agent can
use every route, whatever the gateway says. **This too was found by testing:** before the network rule
existed, a client holding one agent's token read Azure SQL by calling the Functions app directly.

Authorisation lives in one place, the gateway, and the network makes it unavoidable:

- the Functions app has **public network access disabled** and is reachable only through a private
  endpoint;
- the private endpoint subnet's network security group allows **port 443 from API Management's subnet
  only**, so a user on the corporate network or VPN can't reach it either;
- App Service authentication stays on as defence in depth: a request without a valid token is still
  refused.

✅ Smoke test check 8 confirms the backend API is unreachable directly. Don't "fix" this by
re-implementing per-agent checks in every backend: that is the drift rule 1 exists to prevent.

### 3. An agent's identity is a boundary only if nobody else can use it

Per-agent authorisation keys on the token's `azp` claim: which client app requested the token. That
means something only if nobody else can get a token as that app.

- A **confidential client** can't be impersonated without its credential. The Copilot Studio connector
  is one, and it authenticates with a **federated identity credential on a managed identity**, so there
  is no secret to steal. ✅ With the credential removed, sign-in fails (`AADSTS70025`).
- A **public client** has no credential, so anyone in the tenant can get a token with that app's
  `azp`. The agents' client apps have public-client sign-in **off** by default. ✅ A public-client
  sign-in as an agent is refused (`invalid_client`, `AADSTS7000218`).
- The test scripts need public-client sign-in **on**, because they play the agent's part. Turn it on
  for the length of a test run (`-var allow_test_sign_in=true`), then apply again without it. While it
  is on, the agent boundary doesn't hold.
- ⏳ **"Assignment required"** isn't set on the agents' enterprise applications, so any user in the
  tenant can try to use any agent's client app. The data they reach is still limited by rule 4.

**The connector is the agent's identity.** A maker who attaches another agent's connector to their own
agent gets that agent's tools, and the audit trace then names the connector's agent. This was
confirmed with a real agent and is not prevented by the gateway ⏳. Restrict who can use and share each
connector, and cross-check the audit trace against Copilot Studio telemetry
([governance.md](governance.md#known-governance-gaps)).

### 4. Delegated access by default; app-only access only with its own controls

For **delegated tools**, the call runs as the signed-in user. The backend API exchanges the user's
token for a downstream one (the OAuth 2.0 on-behalf-of flow) and calls Microsoft Graph or Azure SQL
with it:

- Graph returns only what that user can see. Azure SQL sees the user and applies their permissions.
  ✅ Smoke test checks 4 and 6.
- A user with no access to the database gets nothing, whatever the agent asks. ✅ Shown by removing the
  Finance Readers group's database access: the next spending query was refused by the database.
- No standing, high-privilege identity sits behind the agent for it to be talked into using (the
  "confused deputy").

For **app-only tools**, the backend API reads as its own managed identity, so the source system can't
tell users apart. Use this only where users have no direct access and the agent is the approved route,
and add the controls the source no longer provides
([architecture.md](architecture.md#what-app-only-access-changes)):

- an **app role** on the user's token, checked at the gateway; ✅ removing the role refuses the next
  fresh token (403);
- a **narrow tool** and a **narrow identity**: the backend API's identity may read one view; ✅ smoke
  test check 9, and removing its database user stops the tool at once.

**Token audience discipline** goes with both. The token the agent sends is valid only for this API
(the `aud` claim is checked by the gateway and by App Service authentication). Downstream tokens are
issued per resource by the on-behalf-of flow. Never forward the user's inbound token to another
service.

### 5. Tools are a prompt-injection surface

The gateway bounds what a manipulated agent can do; it doesn't stop the manipulation. The controls,
the evidence and the gaps are in [ai-safety.md](ai-safety.md). The security-relevant parts:

| Control | Status |
|---|---|
| **The model never writes a query.** `finance_query_spend` takes typed parameters and runs one fixed, parameterised statement; the gateway validates the parameters, and the backend API validates them again | ✅ Smoke test check 12 |
| **Tool descriptions are reviewed like code.** They come from the OpenAPI `description` fields and are instructions to the model | 🔲 A convention, not enforced |
| **The directory and finance tools are read-only** (`GET`). One budgeting tool writes, without an approval gate | ✅ Reads by construction. 🔲 The write is gated by permission only ([ai-safety.md](ai-safety.md#the-write-tool-as-built)) |
| **Tool results are untrusted input to the model.** Rules 1 to 4 limit what a steered agent can reach | ✅ Two crafted results ignored; weak evidence ([ai-safety.md](ai-safety.md#probes)) |
| **Response size cap**, so a tool can't flood the model's context or return data in bulk | ⏳ |
| **Content safety on tool results** (API Management's `llm-content-safety` policy) | ⏳ |

## Network

| Control | Status |
|---|---|
| API Management in **internal virtual network mode**: a private IP address only, and no public DNS record | ✅ Smoke test check 0 |
| The backend API and Azure SQL reachable **only through private endpoints**; public network access disabled | ✅ Smoke test check 8 (backend API); the on-behalf-of calls to Azure SQL use its private endpoint |
| Network security group on the private endpoint subnet: API Management to the backend API only; VPN clients dropped | ✅ Smoke test check 8 |
| Private DNS zone **scoped to the gateway's own name**, never to all of `azure-api.net` | ✅ |
| **Explicit egress** through a NAT gateway (one known public IP address) for Microsoft Entra ID and Graph | ✅ |
| Copilot Studio reaches the private gateway through Power Platform Virtual Network support | ✅ Tested with real agents |
| **Public network access on the two storage accounts** (the Functions app's, and the flow logs') | ⏳ Still enabled, protected by keys. To close, checking that code deployment and the flow-log writer still work |
| Production egress through a firewall with an FQDN allow-list instead of NAT | ⏳ |
| Administrators reach the gateway over corporate connectivity | ✅ for testing, by point-to-site VPN; production would use ExpressRoute or site-to-site VPN |

Only the connector's **API calls** use the virtual network. Its OAuth sign-in and token requests go to
Microsoft Entra ID over the internet. See [networking.md](networking.md).

A fault-injection finding worth knowing: **changing a network security group rule is not a kill
switch.** Rules apply to new connections, and Power Platform reuses warm ones; an explicit deny made
no difference to a running agent for at least two minutes ([operate.md](operate.md#troubleshooting-from-symptom-to-layer)).

## Identity and secrets

| Control | Status |
|---|---|
| The API app registration exposes one delegated scope (`Tools.Read`); agents' client apps are pre-authorised, so users see no consent prompt | ✅ |
| Admin consent for the API's downstream delegated permissions (Graph `User.Read`, Azure SQL `user_impersonation`) | ✅ |
| Azure SQL uses **Microsoft Entra authentication only** (no SQL logins or passwords) | ✅ |
| The on-behalf-of exchange proves itself with a **user-assigned managed identity** (a federated identity credential), not a client secret | ✅ Smoke test check 11: no secret on the Functions app or the app registration. A client secret remains available as a fallback (`obo_credential = "secret"`) |
| The Copilot Studio connector authenticates with a **managed identity and a federated identity credential** | ✅ With the credential removed, sign-in fails (`AADSTS70025`) |
| Agents' client apps have public-client sign-in off | ✅ Refusal demonstrated |
| "Assignment required" on the agents' enterprise applications | ⏳ |
| Least-privilege database access: the backend API's identity may read one view, the Finance Readers group another; nobody else has a database user | ✅ The database refused a user outside the group |
| The VPN uses Microsoft Entra authentication with Conditional Access, not a self-signed certificate | ⏳ |

## Logging without leaking data

| Control | Status |
|---|---|
| Record **who** (the user's object ID, the agent's client app ID) and **what** (tool, decision, status, latency) for every call | ✅ The API policy's audit trace and the gateway logs ([observability.md](observability.md)) |
| **Don't log payloads.** API Management's Application Insights body logging is set to 0 bytes | ✅ Bodies. ⚠️ **Tool arguments** travel in the query string. The gateway log recorded no query string on the rapid profile (Basic v2); not yet checked on the secure profile |
| Copilot Studio telemetry **without** message text (sensitive properties off) | ✅ |
| Alert on authorisation failures | ✅ `authz-denial-spike` fired, and its email arrived |
| MCP server policies must not read `context.Response.Body`: it buffers the stream and breaks MCP | 🔲 A rule for policy authors; the policies here don't |
| Conversation transcripts hold tool results, including data about other people | ⏳ Retention and access not decided |
| The backend APIs return the first 300 characters of a database error to the caller, and so to the model and the transcript | ⏳ Not trimmed: an error could expose schema or object names. Return a fixed message and log the detail instead |

## Abuse limits

| Control | Status |
|---|---|
| Rate limit per agent **and** per user (`rate-limit-by-key`, 30 a minute) | ✅ The first 429 came at call 31 on the Developer tier, and at call 32 or 33 on Basic v2, where the count is approximate |
| A throttled call reaches the agent as tool text inside an HTTP 200, not as an error | ✅ Observed: measure throttling from the gateway logs, not from request failures |
| Quotas per agent | ⏳ |
| Response size cap | ⏳ Listed under [rule 5](#5-tools-are-a-prompt-injection-surface) |

## Where the other concerns are covered

- Who approves a tool or an agent, the data policy, data residency, and how to stop an agent:
  [governance.md](governance.md).
- Prompt injection, silent failure and human oversight: [ai-safety.md](ai-safety.md).
- What is recorded, the queries and the alerts: [observability.md](observability.md).
