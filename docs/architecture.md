# Architecture

Contoso puts one Azure API Management gateway in front of its internal systems, and the gateway serves
them to Copilot Studio agents as **MCP tools**. Each agent gets only its approved tools, every call is
authorised and recorded in one place, and data is read either as the signed-in user (delegated access)
or, where users have no direct access, as the backend API's own identity behind an app-role check
(app-only access). The [README](../README.md) sets out the problem; [concepts.md](concepts.md) explains
the vocabulary.

MCP is an open protocol, so other clients could use the same servers. Copilot Studio is the client this
was built and tested for ([testing.md](testing.md)).

## Components

![Solution architecture: users chat with Copilot Studio agents; each agent's MCP connections sign the user in through Microsoft Entra ID and call the domain MCP servers the agent uses in API Management over a private network; API Management authorises the call and forwards it to the directory and finance API or the separate budgeting API, which exchange the token on behalf of the user and read Microsoft Graph, the finance database or the budgeting database as the user.](diagrams/solution-architecture.svg)

<details>
<summary>Diagram description</summary>

Microsoft Entra ID spans the top: one client app per agent, the API app registration with the
`Tools.Read` scope, and delegated permissions for Microsoft Graph and Azure SQL. Users reach two agents
in Copilot Studio (a Managed Environment with a data policy). Each agent has one MCP connection for
each server it uses, and calls those servers in API Management, inside the private network and reached
through a Power Platform delegated subnet. There are two servers, one for each business domain: the
directory server lists one tool and is used by both agents, and the finance server lists four (cost
centres, spend, forecast get and update) and is used by the Finance Assistant only. The tools map to
the finance and budgeting REST APIs; policies validate the token and apply a
per-agent allow-list, then forward to the backend systems' private endpoints: a directory and finance
API, and a separate budgeting API. Each exchanges the token on behalf of the user to read Microsoft
Graph or its own Azure SQL database (finance, or budgeting for the forecast read and update); only the
finance cost-centre tool reads as a managed identity. Logs from every layer go to one Log Analytics
workspace. The second region's delegated subnet is peered to the main network.
</details>

| Component | Role |
|---|---|
| **API app registration** (`<prefix>-gateway-api`, in Microsoft Entra ID) | The resource the tokens are for. Exposes the delegated scope `Tools.Read` and the app role `CostCentres.Read`. Holds the delegated permissions the backend API needs downstream (Graph `User.Read`, Azure SQL `user_impersonation`), and trusts the backend API's managed identity as its credential |
| **One client app per agent** (`<prefix>-employee-assistant`, `<prefix>-finance-assistant`) | The identity each of the agent's MCP connections signs users in with. Its application ID appears in tokens as the `azp` claim, which the gateway uses to decide which tools the agent may call |
| **API Management** (the gateway) | Imports the REST API once from [openapi.yaml](../backend/openapi.yaml), then exposes one MCP server for each business domain (`directory`, `finance`), each listing that domain's operations as tools and accepting the client apps of the agents that use it. All authorisation happens here |
| **Backend API** (an Azure Functions app) | A plain REST API with no MCP code. Stands in for Contoso's directory/finance systems. Performs the on-behalf-of exchange for downstream calls, proving itself with its user-assigned managed identity (no client secret), and reads the app-only tool's data as that same identity |
| **Budgeting API** (a second Azure Functions app) | A separate Contoso system for cost-centre forecasts. Own OpenAPI, own Function, own SQL database; same Entra audience and gateway policies. Shows fragmented systems behind one front door |
| **Azure SQL** (databases `finance` and `budgeting`) | Microsoft Entra authentication only. Finance authorises the *user* for spending (Finance Readers) and the finance Function's identity for the cost-centre list. Budgeting authorises Budget Editors for forecast read/write; cost-centre codes are duplicated there on purpose |
| **Microsoft Graph** (the directory) | Read as the user, with the delegated permission `User.Read` |
| **Network** (secure profile) | Virtual network, private endpoints, network security groups, NAT egress, private DNS, and a point-to-site VPN for testing. See [networking.md](networking.md) |
| **Power Platform environment** | A Managed Environment in the Australia geography. In the secure profile, two delegated subnets are linked to it by an enterprise policy, so the connector's calls enter the virtual network |
| **Data policy** | An allow-list for that environment: only custom connectors that point at this gateway, plus the Teams channel and Application Insights. See [governance.md](governance.md) |
| **Observability** | One Log Analytics workspace behind API Management, the backend API, the network and Microsoft Entra ID, with Copilot Studio telemetry added per agent. See [observability.md](observability.md) |
| **Assurance (evals)** | Gateway tests show the controls hold; they don't show the agent behaves well. Copilot Studio Evaluate and a probe scorecard cover that. See [testing.md](testing.md#testing-the-agent-evals) |

## A tool call, step by step

1. The user asks a Copilot Studio agent something. The agent decides to call the
   `directory_get_my_profile` tool.
2. The agent's MCP connection for the server that lists the tool sends a `tools/call` to it, for example
   `https://<gateway>/directory-mcp/mcp`, with the user's access token. The token was issued
   to the agent's client app (`azp`) for the API app registration (`aud`) with the scope `Tools.Read`.
3. **MCP server policy** ([mcp-policy.xml.tftpl](../infra/modules/contoso-gateway/policies/mcp-policy.xml.tftpl)):
   rejects the token unless it is from this tenant, for this API, has `Tools.Read`, and was issued to
   the client app of **an agent that uses this server**. Any other app's token gets 401.
4. API Management maps the tool to its REST operation (`GET /directory/me`).
5. **REST API policy** ([api-policy.xml.tftpl](../infra/modules/contoso-gateway/policies/api-policy.xml.tftpl)):
   validates the token again, checks the pair `directory_get_my_profile|<azp>` against the allow-list
   (403 if absent), writes an audit trace (agent, user, operation, allowed or denied) and applies the
   rate limit per agent and user (429). This check also covers direct REST calls; see
   [security.md](security.md#1-authorise-at-the-api-not-only-at-the-mcp-server).
6. API Management forwards the request, with the user's token, to the backend API's **private
   endpoint**.
7. App Service authentication on the Functions app validates the token again (defence in depth).
8. The backend API exchanges the token on behalf of the user for a Microsoft Graph token, calls Graph
   `/me`, and returns the result.
9. API Management returns it to the agent as the MCP tool result.

`finance_query_spend` works the same way with Azure SQL in place of Graph. At step 5 the gateway also
validates the parameters (the category, the date format and a 12-month limit). At step 8 the backend
API exchanges the token for an Azure SQL token and runs one fixed, parameterised statement as the user;
the database refuses anyone who isn't in Contoso Finance Readers.

An app-only tool differs at two steps. At step 5 the policy also requires the user's token to carry
the tool's app role (403 if not). At step 8 the backend API reads Azure SQL as its own managed
identity, with no on-behalf-of exchange. See [Access models](#access-models-delegated-and-app-only).

## The tools

Tool names say what the tool does, in the form `<system>_<action>`, because the agent's orchestrator
chooses a tool from its name and description. The access model (explained in the next section) is stated in
the description, not the name: the orchestrator doesn't need it, and the description is where someone
reading the tool list looks for it.

| Tool | Answers using | Model |
|---|---|---|
| `directory_get_my_profile` | Microsoft Graph | Delegated (on-behalf-of) |
| `finance_list_cost_centres` | The finance database's reference view | App-only (the backend API's managed identity), gated by the `CostCentres.Read` app role |
| `finance_query_spend` | The finance database's spend view, with typed parameters | Delegated (on-behalf-of); the database grants access to the Finance Readers group |
| `budgeting_get_forecast` | The **budgeting** database (a separate Contoso system) | Delegated (on-behalf-of); Budget Editors group |
| `budgeting_update_cost_centre_forecast` | The budgeting database, write | Delegated write (on-behalf-of); Budget Editors; the proc records `updated_by` from `SUSER_SNAME()`. No approval gate in this proof of concept |

The REST paths follow the systems (`/directory/me`, `/finance/cost-centres`, `/finance/spend`), so a
gateway log row maps to a tool at a glance. `/diagnostics/caller` reads the token only; the smoke test
uses it, and it isn't offered to agents as a tool.

## Access models: delegated and app-only

Every tool has to settle one question: **when the backend reads the data, whose permissions apply?**
The Microsoft identity platform has two answers, called delegated access and app-only access.
This proof of concept builds and tests both: four of the [tools](#the-tools) use delegated access and
one uses app-only access, with the controls it needs
([what was built](#what-was-built-and-how-to-demonstrate-it)).

![Two lanes. Delegated access: the agent sends the user's token to API Management, which forwards it to the backend API; the API exchanges it for a token for the user, and Azure SQL or Graph sees the user and applies that user's permissions. App-only access: the same user's token reaches API Management, which also checks who may use the tool; the backend API then uses its own managed identity, and Azure SQL or Graph sees the app and applies the app's permissions.](diagrams/access-models.svg)

<details>
<summary>Diagram description</summary>

Two lanes show the same path from agent to data. In delegated access, the user's token goes from the
agent through API Management to the backend API, which exchanges it (on-behalf-of) for a token for
the user. Azure SQL or Graph sees the user and decides from that user's own permissions. In app-only
access, the user still signs in and the same token reaches API Management, which now also decides which
users may use the tool, by an app role or group on the token. The backend API uses its managed
identity to get its own token, so the source sees the app and decides from the app's permissions, the
same for every user.
</details>

### The two models

| | Delegated access | App-only access |
|---|---|---|
| The backend acts as | The signed-in user | The application's own identity, with no user |
| Permission type | Delegated permissions, also called scopes (`scp` claim) | Application permissions, also called app roles (`roles` claim) |
| What limits it | What the app was granted and what the user can do | Only what the app was granted |
| Who can consent | Users for their own data, or an administrator | An administrator (or the API's owner) |
| The source system sees | The user | The app |
| In this proof of concept | `directory_get_my_profile` and `finance_query_spend` | `finance_list_cost_centres` |

Delegated access reaches another API through the on-behalf-of (OBO) flow. OBO is the mechanism,
delegated access is the model.

### Choosing between them

Microsoft's guidance is to use delegated access when a user works with their own resources or ones
they can reach, and app-only access for automation or when the data can't be scoped to one user. It
also warns that app-only access is broader and more powerful, so use it only where needed, and never
where a user would normally sign in to manage their own resources. For agents it says not to use a
backend identity to bypass user permissions unless there is a clear reason and an explicit control.

| Question | If yes |
|---|---|
| Should users see only what they could already see directly? | Delegated |
| Do users lack direct access on purpose, and the agent is the approved route? | App-only, with the controls below |
| Is the data the same for everyone allowed to use the tool (a catalogue, a policy library)? | App-only fits |
| Does the data differ for each person (HR, a mailbox)? | Delegated. App-only could filter rows by the verified user ID, but that is code you must test, and the source no longer enforces it |

### Access model and credential are separate choices

![A grid. Rows: delegated access and app-only access. Columns: client secret and managed identity. Delegated with a client secret is built and tested here, as the fallback. Delegated with a managed identity is the default, built and tested. App-only with a client secret should be avoided. App-only with a managed identity is for data users cannot reach directly, built and tested.](diagrams/access-matrix.svg)

<details>
<summary>Diagram description</summary>

The row says whose permissions apply; the column says how the backend proves itself to Microsoft
Entra ID. Delegated with a managed identity is what this proof of concept runs by default; delegated
with a client secret is the same exchange with a secret instead, kept as a fallback. App-only with a
secret is the pattern to avoid. App-only with a managed identity is the design for data that users
cannot reach directly.
</details>

A managed identity is a **credential**, not an access model. In a delegated flow it does not replace
the user's token; it replaces only the client secret the API presents next to that token. The user's
permissions still decide what comes back.

What Microsoft documents for the credential:

- The API's app registration gets a **federated identity credential** that trusts the backend API's
  managed identity. Only a **user-assigned** managed identity can be used this way.
- Issuer `https://login.microsoftonline.com/<tenant id>/v2.0`, subject the identity's object
  (principal) ID, audience `api://AzureADTokenExchange`. A wrong subject fails with `AADSTS70021`.
- An application can use such a credential anywhere a client secret could be used, and the OBO flow
  is named. The Azure Identity library's `OnBehalfOfCredential` accepts a client assertion function.
- This is the default here, and tested. A client secret stays available as a fallback
  (`obo_credential = "secret"`).

### What app-only access changes

The source system can no longer tell users apart, so the controls move to the gateway and the
identity.

| Control | Why | Notes |
|---|---|---|
| Who may use the tool, decided at the gateway | The source will answer anyone the app serves | Check an app role on the user's token with `validate-azure-ad-token` `required-claims`. Assign the role to a group, not to the whole tenant. Group assignment needs Entra ID P1 or higher |
| A narrow tool | The model uses whatever latitude it has | A fixed read with no free-form parameters |
| A narrow identity | Its permissions are the blast radius | For SQL, a database user for the identity (`CREATE USER ... FROM EXTERNAL PROVIDER`; display names must be unique) with `SELECT` on one view. For Graph, the smallest application permission, admin-consented |
| The user in the audit trace | The source's own logs show only the app | The gateway records the verified user ID; the backend API can read it from the validated token |
| Revocation is not instant | Microsoft caches a managed identity's tokens per resource for about 24 hours, so changing its role or group membership can take that long | The fast levers are the gateway's allow-list (about 95 seconds to apply here) and removing the database user ([governance.md](governance.md#stopping-an-agent-and-revoking-access)) |
| Entitlement lives in a token | Entitlement lives in the user's token, which is current only when issued | Removing a user from the group takes effect when their access token next refreshes |
| Who can edit the code or policy that holds the identity | Whoever can change it can use the identity. For API Management's own identity, Microsoft says policy editors can use the `authentication-managed-identity` policy to obtain tokens | Restrict write access; keep the identity in the backend API, not in a shared policy |
| The data owner agrees | Users will see data they could not get directly | A decision for the data owner, not the platform team |

### The caller side: how the agent reaches the gateway

The design above keeps the user signing in at the front door, which gives the gateway a verified
user for entitlement and audit, and needs no secret. Microsoft documents these alternatives for a
Copilot Studio tool, and **none has been tried here**:

| Option | What it means | Concern |
|---|---|---|
| End-user credentials (the default; built here) | Each user signs in; the token is theirs | None for this design |
| Maker-provided credentials | The agent runs with the maker's connection for every user | Others act with the maker's permissions; Copilot Studio's security scan flags it and an administrator can disable it |
| A service principal connection on a custom connector | A connection that is not a user | Learn describes service principal support for custom connectors, and a separate page says the client credentials grant isn't supported by them. The two aren't reconciled, and whether it works for MCP tools, or with a managed identity, is unknown |
| API key | A header or query key | It is a secret |

An agent that runs with no user at all (a scheduled or event-triggered one) is a third case, covered
in [going-further.md](going-further.md#agents-that-run-without-a-user).


### Where this proof of concept stands

| Combination | Status |
|---|---|
| Delegated, managed identity (the default) | ✅ The directory and the database both see the user; no secret anywhere. By script and through Copilot Studio |
| App-only, managed identity | ✅ The database sees the backend API's identity. The role check, and revocation at the gateway and at the source, were tested |
| Delegated, client secret (the fallback, `obo_credential = "secret"`) | ✅ Identical results |
| App-only, client secret | Not built: avoid it |

The evidence is in [testing.md](testing.md#access-models-and-revocation).

### What was built, and how to demonstrate it

| Piece | Where | Notes |
|---|---|---|
| The backend API's identity | A user-assigned managed identity, [backend.tf](../infra/modules/contoso-gateway/backend.tf) | Trusted by the API app through a federated identity credential ([identity.tf](../infra/modules/contoso-gateway/identity.tf)). Used for the on-behalf-of exchange and as the app-only identity |
| The switch | `obo_credential`: `managed_identity` (default) or `secret` | The secret exists only in `secret` mode |
| The app-only tool | `finance_list_cost_centres`, `GET /finance/cost-centres` ([function_app.py](../backend/function_app.py)) | Reads `finance.v_cost_centres` as the identity; returns the rows, `queried_as`, `database_user` and `requested_by`. Finance Assistant only |
| The delegated tool | `finance_query_spend`, `GET /finance/spend?category&from&to` | Runs one fixed, parameterised statement against `finance.v_spend` as the user; returns totals per category and `queried_as` |
| The data and grants | [sql-setup.py](../scripts/sql-setup.py) | Schema `finance`: cost centres and about a year of spending, one view per tool. The identity gets `SELECT` on the cost-centres view only; the Finance Readers group on the spend view only. No person can read the cost-centres view directly, which is the point of the app-only tool |
| Who may use the app-only tool | App role `CostCentres.Read`, assigned to `cost_centres_user_upns` (default: the maker) | The API policy requires it for the tools in `tool_roles`. A user without it gets a 403 in the gateway log. Assigning the role to a group needs Entra ID P1 |
| Who may query spending | The Finance Readers Entra group, `finance_reader_upns` (default: the maker) | The database decides: anyone outside the group is refused by the database itself, after the gateway has let the call through |
| Servers and who uses them | `server_definitions` and `agent_definitions` in [main.tf](../infra/modules/contoso-gateway/main.tf) | A server lists its tools to every agent that uses it; an agent's tools are the union of its servers'. The allow-list still decides per agent |

| # | Do | Expect | Shows |
|---|---|---|---|
| 1 | Ask the Finance Assistant who you are, then how much was spent on travel | Both answers come from the systems as you; no client secret on the backend API or the app | Delegated access; the managed identity is only the credential |
| 2 | Ask for the cost centres | Rows, with `database_user` the backend API's identity | App-only access in the same chat |
| 3 | Remove the Finance Readers group's database user (`sql-setup.py --revoke-readers`), ask about spending again | Refused by the database (`database_refused`); the cost centres still work | The backend's own rules; app-only doesn't depend on the user's access |
| 4 | Remove your app role (`cost_centres_user_upns=[]`), ask straight away, then with a fresh sign-in | Works until the token refreshes; then a 403 from the gateway | Revocation follows the token |
| 5 | Ask the Employee Assistant for the cost centres | Not available: the tool isn't on its list | Per-agent scoping |
| 6 | Ask for spending over more than 12 months | Rejected by the gateway before the database sees it | Parameter validation at the gateway |
| 7 | Remove the identity's database user (`sql-setup.py --revoke-identity`) | `finance_list_cost_centres` fails (`app_only_connect_failed`) | Where app-only access is revoked |

Run `sql-setup.py` again to restore both grants.

### Learn more: access models

- [Permissions and consent overview](https://learn.microsoft.com/entra/identity-platform/permissions-consent-overview) ·
  [Delegated access](https://learn.microsoft.com/entra/identity-platform/delegated-access-primer) ·
  [App-only access](https://learn.microsoft.com/entra/identity-platform/app-only-access-primer)
- [Access patterns and controls for AI agents](https://learn.microsoft.com/startups/build/identity-management/access-patterns-controls)
- [Configure an application to trust a managed identity](https://learn.microsoft.com/entra/workload-id/workload-identity-federation-config-app-trust-managed-identity) ·
  [On-behalf-of flow](https://learn.microsoft.com/entra/identity-platform/v2-oauth2-on-behalf-of-flow)
- [Use managed identities in API Management](https://learn.microsoft.com/azure/api-management/api-management-howto-use-managed-service-identity) ·
  [Validate Microsoft Entra token](https://learn.microsoft.com/azure/api-management/validate-azure-ad-token-policy)
- [Add app roles and receive them in the token](https://learn.microsoft.com/entra/identity-platform/howto-add-app-roles-in-apps) ·
  [Use managed identities for App Service and Azure Functions](https://learn.microsoft.com/azure/app-service/overview-managed-identity)
- [Control maker-provided credentials](https://learn.microsoft.com/microsoft-copilot-studio/configure-no-maker-authentication)

## Design decisions

| Decision | Why | Alternative considered |
|---|---|---|
| **One MCP server per business domain**; an agent uses the servers it needs | Each tool is defined once, a system's owner owns one server, and a new agent reuses existing servers | One server per agent: the agent's tool list is exact, but shared tools such as the directory profile are duplicated on every server. One server per backend system: finer, but more connectors for an agent that spans systems (here, finance and budgeting share one server) |
| **Authorisation in API Management; the backend trusts only the gateway** | One rule set, generated from one map. Backends stay plain REST APIs | Per-route checks in every backend: duplicated, and they drift |
| **Delegated access by default** (the on-behalf-of flow) | Source systems keep enforcing their own permissions for each user | App-only access with the backend API's managed identity: the source can no longer tell users apart, so the gateway must add its own check. Right only where users have no direct access ([Access models](#access-models-delegated-and-app-only)) |
| **REST to MCP in API Management, not MCP code in each backend** | Existing APIs become tools without changes | An MCP SDK in each service: more code, and more places to secure |
| **A fully private gateway** (secure profile) | The constraint: agents reach internal systems with no public data-plane endpoint | A public gateway with Microsoft Entra authentication: simpler, and Copilot Studio needs no virtual network setup, but it breaks the constraint. The rapid profile does this, for development only |
| **Two profiles from one module** | The secure profile is what an organisation would run; the rapid profile deploys the same gateway, identities and policies in minutes for iteration | Two separate configurations: they would drift |
| **API Management Developer tier, internal virtual network mode** (secure profile) | The cheapest tier that keeps the gateway private, for a proof of concept | Premium (classic), Premium v2 with virtual network injection, or Standard v2 with a private endpoint: all meet the constraint and differ in resilience and support ([going-further.md](going-further.md#the-constraint-every-choice-has-to-meet)) |
| **A custom MCP connector per agent and server, all on the agent's own client app** | Each agent keeps its own identity, so the gateway can tell agents apart, whichever server it calls | One connector shared by several agents: the gateway couldn't distinguish them |
| **A DNS forwarder VM for VPN clients** | Cheap, and enough for a proof of concept | Azure DNS Private Resolver, at a higher cost |
| **Tool names say what the tool does** (`<system>_<action>`); the access model is in the description | The agent's orchestrator chooses a tool from its name and description | Access model in the name: noise for the orchestrator |

## The two deployment profiles

One Terraform module holds the whole solution. Two thin root configurations call it, each with its own
state, and one input decides the network:

- `private_networking = { ... }` builds the secure profile;
- `private_networking = null` builds the rapid profile.

```
infra/
  modules/contoso-gateway/       the whole solution
    main.tf                      settings derived from the profile; the agents and their tools
    identity.tf  backend.tf  gateway.tf  powerplatform.tf  governance.tf  observability.tf
    network/                     secure profile only: virtual network, subnets, NSGs, NAT, private DNS
                                 and endpoints, Power Platform delegated subnets, flow logs, VPN
  profiles/
    secure/                      private networking, VPN, API Management in internal mode
    rapid/                       public endpoints, for fast build, test and teardown
```

| | `secure` | `rapid` (development only) |
|---|---|---|
| API Management | Developer tier, internal virtual network mode | Basic v2, public |
| Backend API and database | Private endpoints, public network access off | Public endpoints with Microsoft Entra authentication; the database behind a firewall rule for named addresses |
| Network, VPN, DNS forwarder | Yes | None |
| Power Platform | Enterprise policy linked to the environment | Not linked |
| Identity, the on-behalf-of flow, app role, allow-lists, parameter validation, rate limits, logs, alerts | Yes | Identical |
| Build | About an hour | About 11 minutes |

The module derives everything else (public network access, private endpoints, the enterprise policy
link) from that one input, so the two profiles can't disagree about what "private" means.

**The rapid profile proves identity and policy, not the network.** It can't find faults in private DNS,
delegated subnets or the delay after linking the enterprise policy. It also behaves slightly
differently at the gateway: rate limits on the v2 tiers are approximate
([AGENTS.md](../AGENTS.md#api-management-behaviour-worth-knowing)).

## Cost of this demonstration

Secure profile, Australia East, retail prices, while the stack is running:

| Item | US$ a month | Notes |
|---|---|---|
| API Management Developer (internal virtual network mode) | ~48 | No SLA; production uses Premium or Premium v2 |
| VPN gateway VpnGw1AZ | ~140 | **Testing access only**; drop it if you already have corporate connectivity into the virtual network |
| Private endpoints (5) | ~37 | |
| NAT gateway | ~33 | Explicit egress for Microsoft Entra ID and Graph |
| DNS forwarder VM | ~11 | Lets VPN clients resolve private names |
| Azure SQL Basic | ~5 | |
| Functions (Flex Consumption), Log Analytics | usage-based, small | |
| **Total** | **~275** | **~135 without the VPN gateway.** Lab cost only: production API Management, licences and Copilot Studio capacity are not comparable |

The rapid profile has no network, VPN or DNS forwarder. Its main cost is API Management Basic v2 (about
US$150 a month at list price), plus a little for Azure SQL and Functions.

## Files

| File | What it defines |
|---|---|
| [profiles/secure/main.tf](../infra/profiles/secure/main.tf), [profiles/rapid/main.tf](../infra/profiles/rapid/main.tf) | The two root configurations: providers and one module call each. Their `variables.tf` and `outputs.tf` are identical ([check-profiles.sh](../scripts/check-profiles.sh)) |
| [terraform.tfvars.example](../infra/profiles/secure/terraform.tfvars.example) | The local values you supply (the maker's account, the Copilot Studio connectors) |
| [main.tf](../infra/modules/contoso-gateway/main.tf) | Settings derived from the profile, and the server and agent maps: which agent uses which servers and tools |
| [variables.tf](../infra/modules/contoso-gateway/variables.tf) | The module's inputs |
| [identity.tf](../infra/modules/contoso-gateway/identity.tf) | The API app registration, the agents' client apps, admin consent, the app role, the Finance Readers group |
| [backend.tf](../infra/modules/contoso-gateway/backend.tf) | The Functions app (App Service authentication, virtual network integration in the secure profile), storage, Application Insights, Azure SQL |
| [gateway.tf](../infra/modules/contoso-gateway/gateway.tf) | The API Management instance, the REST API import, MCP servers, tools, policies |
| [powerplatform.tf](../infra/modules/contoso-gateway/powerplatform.tf) | The Power Platform environment, Managed Environment settings, the enterprise policy link, the connectors' federated identity credentials |
| [governance.tf](../infra/modules/contoso-gateway/governance.tf) | The data policy for the agents' environment |
| [observability.tf](../infra/modules/contoso-gateway/observability.tf) | Logging to Application Insights and Log Analytics, the Microsoft Entra diagnostic setting, alerts |
| [network/](../infra/modules/contoso-gateway/network/) | Secure profile only: the virtual network, private DNS and endpoints ([main.tf](../infra/modules/contoso-gateway/network/main.tf)); the DNS forwarder and VPN gateway ([vpn.tf](../infra/modules/contoso-gateway/network/vpn.tf)); the Power Platform delegated subnets ([powerplatform.tf](../infra/modules/contoso-gateway/network/powerplatform.tf)); flow logs ([flowlogs.tf](../infra/modules/contoso-gateway/network/flowlogs.tf)) |
| [api-policy.xml.tftpl](../infra/modules/contoso-gateway/policies/api-policy.xml.tftpl) | The REST API policy: authorisation on every path, and the spending query's parameter checks |
| [mcp-policy.xml.tftpl](../infra/modules/contoso-gateway/policies/mcp-policy.xml.tftpl) | The policy on each MCP server |
| [openapi.yaml](../backend/openapi.yaml) | The finance/directory REST API; its operation descriptions become tool descriptions |
| [function_app.py](../backend/function_app.py) | The finance/directory backend |
| [budgeting/openapi.yaml](../backend/budgeting/openapi.yaml), [budgeting/function_app.py](../backend/budgeting/function_app.py) | The budgeting system (separate API and Function) |
| [sql-setup.py](../scripts/sql-setup.py), [sql-setup-budgeting.py](../scripts/sql-setup-budgeting.py) | Finance and budgeting schemas, sample data and database users |
| [smoke.py](../scripts/smoke.py), [pressure.py](../scripts/pressure.py), [vpn.sh](../scripts/vpn.sh), [deploy-function.sh](../scripts/deploy-function.sh) | Testing and deployment ([testing.md](testing.md)). Scripts take `--profile rapid`; the default is `secure` |
