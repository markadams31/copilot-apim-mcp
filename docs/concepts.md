# Concepts

This solution joins three platforms (Microsoft Copilot Studio, Azure API Management and Microsoft
Entra ID), and each brings its own vocabulary. This page explains the concepts you need to review
the design, in plain language first and technical detail second.

**Find your section:**

| You are… | Start with | Then read |
|---|---|---|
| **Security** | [Tokens, scopes and claims](#tokens-scopes-and-claims), [On-behalf-of](#on-behalf-of-obo), [Managed identity and federated identity credentials](#managed-identity-and-federated-identity-credentials) | [security.md](security.md), [architecture.md](architecture.md#access-models-delegated-and-app-only) |
| **Enterprise architecture** | [MCP](#mcp-and-tools), [API Management as an MCP server](#api-management-as-an-mcp-server) | [architecture.md](architecture.md) |
| **Governance / risk** | [Power Platform environment](#power-platform-environment), [Managed Environment](#managed-environment), [Connectors and connections](#custom-connectors-and-connections) | [governance.md](governance.md) |
| **Networking** | [Enterprise policy and subnet delegation](#enterprise-policy-and-subnet-delegation) | [networking.md](networking.md) |
| **AI / agent team** | [MCP](#mcp-and-tools), [Connectors and connections](#custom-connectors-and-connections), [Agent identities](#agent-identities-two-different-things) | [ai-safety.md](ai-safety.md), [testing.md](testing.md#testing-the-agent-evals), [add-mcp-tool-to-agent.md](add-mcp-tool-to-agent.md) |
| **Power Platform admins** | [Power Platform environment](#power-platform-environment) through [Data policies](#data-policies) | [deploy.md](deploy.md#prerequisites) |
| **API owners** | [API Management as an MCP server](#api-management-as-an-mcp-server), [On-behalf-of](#on-behalf-of-obo) | [operate.md](operate.md#tools-servers-and-agents), [architecture.md](architecture.md#access-models-delegated-and-app-only) |

## The big picture

1. A **Copilot Studio agent** at Contoso needs data from internal systems, which already have
   **REST APIs**.
2. **Azure API Management** (the gateway) publishes chosen API operations as **MCP tools**, grouped
   into **MCP servers**. Each server offers the tools one agent is approved for.
3. When a user chats with the agent, the agent's **connector** signs the user in with **Microsoft
   Entra ID** and receives an **access token** that says *which user*, *which agent* and *what it may
   do* (the **scope**).
4. The gateway checks that token and the agent's **allow-list**, then forwards the call over a
   **private network** to the **backend API**.
5. The backend API **acts on behalf of the user** when it reads the data, so the user's own
   permissions apply. For data users can't reach themselves, it reads with its own identity instead,
   after the gateway has checked an **app role** on the user's token.
6. No password or client secret is stored anywhere. The connector, and the backend API, each prove
   who they are with a **managed identity** that Microsoft Entra ID trusts through a **federated
   identity credential**.

## MCP and tools

The Model Context Protocol (MCP) is an open standard for how an AI agent
discovers and calls *tools*: actions such as "look up this employee" or "list my open tickets".
An **MCP server** offers a list of tools, each with a name, a description and its inputs. The agent's
language model reads the descriptions and decides when to call which tool.

**In this solution:** one MCP server for each business domain, for example
`https://<gateway>/finance-mcp/mcp`. Each agent has its own client app and one connector for each server
it uses, so the Finance Assistant uses the directory and finance servers and the Employee Assistant uses
the directory server only.

**Why it matters:**
- One standard, many clients. The same tools work from Copilot Studio, Visual Studio Code, or any
  MCP-capable agent, so integrations are built once.
- **Tool descriptions are instructions to the model.** A misleading description changes what the
  agent does. Review them like code.

**Agents and servers are many-to-many.** The gateway enforces two things. A server accepts the tokens of
the client apps of the agents that use it, and the allow-list is a set of (operation, app) pairs that
decides which tool each agent may call. So:

- An agent can use several servers (Copilot Studio supports it), with one connector for each. All of an
  agent's connectors use that agent's own client app, so the gateway still sees one identity.
- Several agents can use one server. It lists the same tools to each of them, and the allow-list decides
  who may call what.
- Several agents can't share one *connector*: the connector is the identity, so the gateway couldn't tell
  them apart (confirmed by test: an agent using another agent's connector gets that agent's tools).
- Servers could instead follow each backend system, or each agent. Grouping by **business domain** (here
  directory and finance, with budgeting in finance) defines each tool once and keeps the server count
  low; see [assumptions worth challenging](going-further.md#assumptions-worth-challenging).

**Learn more:** [MCP servers in API Management](https://learn.microsoft.com/azure/api-management/mcp-server-overview) ·
[Connect Copilot Studio to an MCP server](https://learn.microsoft.com/microsoft-copilot-studio/mcp-add-existing-server-to-agent)

## API Management as an MCP server

Azure API Management (API Management) is the organisation's API gateway. It can take
an existing REST API and publish selected operations as MCP tools, with no change to the API itself.
Every call passes through API Management, where policies check identity, apply limits and log activity.

**In this solution:**
- The backend API is imported into API Management once, from its OpenAPI description.
- Each MCP server accepts one client app (here, one agent's) and exposes that app's approved operations as tools.
- **The same API is also reachable as plain REST** (`/tools/...`). So the authorisation rules live on
  the API itself, where they apply to both paths. See
  [security.md, rule 1](security.md#1-authorise-at-the-api-not-only-at-the-mcp-server).

**Why it matters:** API Management is the **single control point**. Authentication, per-agent authorisation,
rate limits and audit logging are configured once, not in every agent or backend.

Microsoft groups this under the API Management **AI gateway** capabilities. What else in that set
applies here, and how it differs from the separate AI Gateway preview product, is in
[going-further.md](going-further.md#microsofts-ai-gateway-offerings-measured-against-this-design).

**Learn more:** [AI gateway in Azure API Management](https://learn.microsoft.com/azure/api-management/genai-gateway-capabilities) ·
[Expose a REST API as an MCP server](https://learn.microsoft.com/azure/api-management/export-rest-mcp-server) ·
[Secure access to MCP servers](https://learn.microsoft.com/azure/api-management/secure-mcp-servers)

## App registrations and service principals

Before an application can sign users in or be called with a token, it's
registered in Microsoft Entra ID. The **app registration** is its definition (name, what it exposes,
what it may call); the **service principal** (enterprise application) is its instance in the tenant,
where consent and user assignment are recorded.

**In this solution:**

| Registration | Role | What it holds |
|---|---|---|
| **API app registration** (`<prefix>-gateway-api`) | The *resource*: the thing being protected | The scope `Tools.Read`; the app role `CostCentres.Read`; delegated permissions to call Microsoft Graph and Azure SQL on the user's behalf |
| **One client app per agent** (`<prefix>-employee-assistant`, `<prefix>-finance-assistant`) | The *client*: who's asking | Permission to request `Tools.Read`; the agent connector's redirect URL and federated identity credential |

**Learn more:** [Application and service principal objects](https://learn.microsoft.com/entra/identity-platform/app-objects-and-service-principals)

## Tokens, scopes and claims

When the user signs in through an agent, Entra ID issues an **access token**:
a signed, short-lived statement that API Management can verify without calling anyone. A **scope** is a named
permission an API offers (here `Tools.Read`, meaning "use Contoso's agent tools as the signed-in user"); the
client asks for it, and the token records that it was granted.

The token's **claims** are what API Management decides on:

| Claim | Means | Example | Checked by |
|---|---|---|---|
| `aud` (audience) | Which API the token is for | the API app registration | API Management, backend |
| `azp` (authorized party) | Which client app asked for it, i.e. **which agent** | finance-assistant's app ID | API Management: picks the MCP server and the allow-list |
| `scp` (scope) | What the user delegated | `Tools.Read` | API Management |
| `oid`, `upn` | Who the user is | the signed-in employee | backend, audit logs |
| `tid` | Which tenant issued it | your tenant | API Management |

**Delegated and app-only access.** In *delegated access* the app acts as a signed-in user (scopes /
`scp`). In *app-only access* it acts as itself. This solution uses delegated access for directory,
spend and budgeting tools, and app-only for cost centres (gateway checks an app role, then the
backend reads as itself). [architecture.md](architecture.md#access-models-delegated-and-app-only) compares the two.

**Pre-authorisation and consent.** Each agent app is **pre-authorised** for `Tools.Read`, so users
aren't asked to consent. An administrator granted **admin consent** for the API to call Graph and
SQL on users' behalf.

![Sequence diagram of a tool call: the agent sends tools/call with a bearer token to API Management, which validates the token, checks the agent and the allow-list, applies the rate limit and writes the audit trace, then forwards the call with the same token to the backend API and returns the result.](diagrams/auth-tool-call.svg)

<details>
<summary>Diagram description</summary>

The agent calls its MCP server with the access token. API Management validates the token's
signature, tenant, audience and scope; checks that the `azp` claim is the agent this server belongs to
and that the operation is on that agent's allow-list; applies the per-agent, per-user rate limit and
writes an audit trace. It then forwards the call and the same token to the backend API and returns
the result. A failed check stops the call at API Management: 401 for the token, 403 for the
allow-list, 429 for the limit.
</details>

**Learn more:** [Scopes and permissions](https://learn.microsoft.com/entra/identity-platform/scopes-oidc) ·
[Access token claims](https://learn.microsoft.com/entra/identity-platform/access-token-claims-reference)

## On-behalf-of (OBO)

The token at the gateway is only valid for the backend API. To call Graph or Azure SQL **as the same
user**, the backend exchanges that token for a new one (OAuth 2.0 on-behalf-of). Each system then
applies **that user's** permissions. The alternative, a powerful app identity for everything, would
bypass data rules.

Full comparison of delegated vs app-only, and when OBO applies:
[architecture.md](architecture.md#access-models-delegated-and-app-only). Diagram: [auth-obo.svg](diagrams/auth-obo.svg).

**Learn more:** [On-behalf-of flow](https://learn.microsoft.com/entra/identity-platform/v2-oauth2-on-behalf-of-flow)

## Managed identity and federated identity credentials

Instead of a client secret, the connector (and the backend's OBO exchange) prove who they are with a
**managed identity**. A **federated identity credential** on the app registration tells Entra ID to
trust tokens from that identity's issuer + subject (`api://AzureADTokenExchange`). No secret exists;
without a matching subject, sign-in fails with `AADSTS70025`.

A managed identity is a **credential**, not an access model: it does not change whose permissions
apply ([architecture.md](architecture.md#access-model-and-credential-are-separate-choices)). Maker
steps to turn the connector onto managed identity and register the subject:
[add-mcp-tool-to-agent.md](add-mcp-tool-to-agent.md). Sign-in diagram:
[auth-sign-in.svg](diagrams/auth-sign-in.svg).

**Learn more:** [Workload identity federation](https://learn.microsoft.com/entra/workload-id/workload-identity-federation) ·
[Managed identities for Azure resources](https://learn.microsoft.com/entra/identity/managed-identities-azure-resources/overview)

## Agents and harnesses

Every Copilot Studio agent runs on a **harness**: the runtime between the agent's definition and the
language model. It decides when to call the model, what to send it and which tools to call. The
harness is chosen when the agent is created and affects features and billing. This solution uses the
**Microsoft Copilot harness** (formerly the GitHub Copilot harness) for its
agents; the **standard harness** runs rule-based agents with topics. The official
[harness overview](https://learn.microsoft.com/microsoft-copilot-studio/harnesses-overview) compares
them, and [deploy.md](deploy.md#which-harness-and-copilot-credits) covers billing here.

An agent on the Microsoft Copilot harness is built from a few parts, which Microsoft documents in detail:

| Part | What it is | What governs it here |
|---|---|---|
| **Instructions and model** | What the agent is for, and the model that reasons | The model is a [what still depends on the model](ai-safety.md#what-still-depends-on-the-model) risk |
| **Tools** | Actions the agent can call, including MCP servers | The gateway: the allow-list and the user's permissions |
| **Knowledge** | Sources the agent reads, such as websites and files | The environment's [data policy](#data-policies) |
| **Skills** | Reusable capabilities the agent can use ([Skills overview](https://learn.microsoft.com/microsoft-copilot-studio/agents-experience/skills-overview)) | Not examined here |
| **Channels** | Where users reach the agent, such as Teams | The data policy, and the agent's sharing limits |

## Agent identities: two different things

The two are easy to confuse:

| | **Entra Agent ID** | **Agent client app** (this solution) |
|---|---|---|
| What | An identity Copilot Studio creates automatically for every agent | An app registration Contoso creates, one per agent |
| Used for | The agent talking to channels and Microsoft services; governance, Conditional Access (Teams channel today), audit | Signing users in for the MCP connection, so the token's `azp` identifies the agent |
| Who controls it | Microsoft manages its credentials; admins govern it in Entra | Contoso, in Terraform |

**Learn more:** [Agent identities in Copilot Studio](https://learn.microsoft.com/microsoft-copilot-studio/govern-agents-identities-overview)

## Power Platform environment

Copilot Studio is part of Microsoft Power Platform. An **environment** is a
container (a workspace with its own database, Dataverse) that holds agents, connectors,
connections and their settings, in one geographic location. Who can build there, which connectors
are allowed and which network the agents use are all set **per environment**.

**Types:** Default (everyone in the tenant; avoid for governed work), Developer (for one maker),
Sandbox, Production and Trial. **Trial environments can't use Virtual Network support.**

**In this solution:** an environment in the **Australia** geography, with Dataverse, created by
Terraform. It is a Sandbox by default: pay-as-you-go billing and the Microsoft Copilot harness need a
Sandbox or Production environment, not Developer. Data residency settings are explicit: generative AI
may not move data across regions, and Bing-backed features are off.

**Learn more:** [Environments overview](https://learn.microsoft.com/power-platform/admin/environments-overview)

## Managed Environment

A premium governance layer switched on per environment. It adds controls
that ordinary environments lack, such as limits on how widely agents can be shared, usage insights,
solution checks, and **it's required for Virtual Network support**.

**In this solution:** agents can be shared with at most 10 named users and never with whole
security groups ([governance.md](governance.md#managed-environment)).

**Learn more:** [Managed Environments overview](https://learn.microsoft.com/power-platform/admin/managed-environment-overview)

## Enterprise policy and subnet delegation

Copilot Studio runs in Microsoft's cloud, so by default its connectors call
APIs over the internet. **Power Platform Virtual Network support** changes that: you **delegate** a subnet in
your own Azure virtual network to Power Platform, and the environment's connectors then run *inside
that subnet*, with private IP addresses, so they can reach private resources such as an internal
API Management instance.

- **Subnet delegation** hands a subnet to a specific Azure service (here
  `Microsoft.PowerPlatform/enterprisePolicies`).
- An **enterprise policy** (kind `NetworkInjection`) is an Azure resource that names the delegated
  subnets. It's **linked** to one or more Power Platform environments.
- Geographies with two Azure regions need **two delegated subnets, one in each** (Australia:
  australiaeast and australiasoutheast), so Power Platform can fail over.
- Only the connector's **API calls** use the subnet; OAuth sign-in and token requests go to Entra ID
  over the internet.

**Learn more:** [Virtual Network support overview](https://learn.microsoft.com/power-platform/admin/vnet-support-overview) ·
[Set up Virtual Network support](https://learn.microsoft.com/power-platform/admin/vnet-support-setup-configure)

## Custom connectors and connections

When you add an MCP server to an agent, Copilot Studio creates a **custom
connector**: the definition of how to call that server, including how to authenticate. When a user
first uses the tool, they create a **connection**: the connector plus their own sign-in.

- **End-user credentials** (the default, and what the tests here use): each user signs in as
  themselves. Nothing here yet stops a maker choosing the other option; see
  [governance.md](governance.md#known-governance-gaps).
- **Maker-provided credentials**: everyone uses the maker's sign-in. This lets users see what the
  *maker* can see, so admins can turn the option off per environment.

**Learn more:** [Control maker-provided credentials](https://learn.microsoft.com/microsoft-copilot-studio/configure-no-maker-authentication)

## Data policies

Data policies (formerly DLP policies) decide which connectors may be used in
an environment, and which may be combined. Because an MCP server in Copilot Studio is a connector,
**a data policy can block an MCP server**, per environment or tenant-wide.

**In this solution:** an allow-list on the agents' environment: only custom connectors on this API
Management, the Teams channel and Application Insights are allowed; everything else is blocked by
default. Adding a public website as knowledge was refused with `DataLossPreventionViolation`
([governance.md](governance.md#the-data-policy)).

**Learn more:** [Data policies for agents](https://learn.microsoft.com/microsoft-copilot-studio/admin-data-loss-prevention)
