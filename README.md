# A secure gateway between Copilot Studio agents and your internal systems

This repository is a proof of concept for a hypothetical organisation, Contoso, whose data is spread
across many separate internal systems. Contoso wants its **Microsoft Copilot Studio agents** to use
those systems securely, with **Azure API Management as the gateway** between them. The systems stay
private, agents hold no credentials, each agent gets only the tools it is approved for, and every
call is recorded.

The proof of concept was built and tested to answer five questions:

| Question | Page |
|---|---|
| Can an agent, or someone holding its token, reach more than it should? | [Security](docs/security.md) |
| Who decides what an agent may do, and how is it stopped? | [Governance](docs/governance.md) |
| Can we see what every agent did, for whom? | [Observability](docs/observability.md) |
| What happens when the model is wrong, manipulated or silently failing? | [AI safety](docs/ai-safety.md) |
| How do we know the agent is performing, and that a change did not make it worse? | [Evals](docs/testing.md#testing-the-agent-evals) |

The evidence for every claim, and the claims not yet tested, are in [docs/testing.md](docs/testing.md).

## The problem

Contoso's information lives in many internal systems: a directory, a finance database, a budgeting and
forecasting tool, a service desk, an ageing HR system and more. Each has its own sign-in and interface.
Many tasks mean pulling data from several of them then reasoning over it with internal policy to form a decision.

Contoso wants Copilot Studio agents to help its staff with that work. Early experiments showed that an
agent has to reach internal data and systems to be useful beyond answering general questions.

Connecting each agent directly to each system creates problems that grow with every agent and every
system:

| Without a gateway | Why it hurts |
|---|---|
| A bespoke connection from each agent to each system | Every new agent repeats the integration work |
| Agents hold credentials for the systems | Secrets spread to places that are hard to audit or rotate |
| Access rules re-implemented in each agent | Rules drift, and one missed check is a data leak |
| Systems opened to the internet so agents can reach them | Internal systems lose their main protection |
| No single record of what an agent did | Nobody can answer "which agent read this, for whom?" |

## The answer: a gateway

Put **one front door between the agents and the systems**. API Management publishes the systems'
operations as **tools** an agent can call, using the Model Context Protocol (MCP), and in the same
place:

- **decides which agent may call which tool**, and for which user, from one allow-list;
- **checks the request before any system sees it**: the token, an app role where needed, the
  parameters;
- **limits the rate** per agent and user, so a runaway agent can't flood a system;
- **records every call**: which user, which agent, which tool, and the outcome;
- **keeps the systems private**: they accept traffic from the gateway only, and agents never see their
  credentials.


![Solution architecture: users chat with Contoso's agents in Copilot Studio; each agent's MCP connections sign the user in through Microsoft Entra ID and call the domain MCP servers the agent uses in API Management over a private network; API Management authorises the call and forwards it to the directory and finance API or the separate budgeting API, which read Microsoft Graph and their own databases as the user, or read reference data as themselves.](docs/diagrams/solution-architecture.svg)

The components and a step-by-step tool call are in [docs/architecture.md](docs/architecture.md).

## The demonstration

The demonstration has three systems (the directory, finance and budgeting), two agents and five tools.
Finance and budgeting have separate backends and databases, as in a fragmented estate. Each tool shows
one thing the gateway does.

| Agent | For | MCP servers it uses |
|---|---|---|
| **Contoso Employee Assistant** | Everyone | `directory` |
| **Contoso Finance Assistant** | Budget holders | `directory` and `finance` |

There is one MCP server for each business domain, so each tool is defined once. The `directory` server
lists `directory_get_my_profile`. The `finance` server lists the other four tools, including the two
that read and write the separate budgeting system.

| Tool | System | Access | What it shows |
|---|---|---|---|
| `directory_get_my_profile` | Directory (Microsoft Graph) | As the user (delegated access) | The agent acts as the user, with no secret anywhere |
| `finance_list_cost_centres` | Finance database, cost-centre view | As the backend API (app-only access), behind an app role | Data users can't query directly; the gateway decides who may use it |
| `finance_query_spend` | Finance database, spending view | As the user (delegated access) | A parameterised query: the model fills typed parameters, never SQL; the gateway validates them; the database decides who may see spending |
| `budgeting_get_forecast` | Budgeting database (a separate system) | As the user (delegated access) | A second Contoso system behind the same gateway; only Budget Editors may read |
| `budgeting_update_cost_centre_forecast` | Budgeting database | As the user (delegated write) | A write tool: typed parameters, and the database records who changed the forecast. There is no approval gate |

A conversation with the Finance Assistant, and what each step demonstrates:

| The user asks | What it shows |
|---|---|
| "Who am I, and which department am I in?" | The directory is read as the user |
| "What cost centres are there?" | App-only access, behind an app role checked at the gateway |
| "How much did we spend on travel since July?" | The database is queried as the user, with parameters validated at the gateway |
| "And for 2023 to 2026?" | Rejected by the gateway (more than 12 months) before the database sees it |
| "What is the Platform engineering forecast for this year?" | The budgeting system is read as the user (a separate backend from finance) |
| "Set that forecast to 421000" | Delegated write; the budgeting database records who made the change |
| (after removal from Contoso Finance Readers) "How much did we spend?" | Refused by the database itself: the system's own rules still apply |

The Employee Assistant can't answer "What cost centres are there?": the tool isn't on its list.

## How a tool call works

1. A user chats with an agent, in the Copilot Studio test pane or, once it is published, in Teams.
2. The agent's MCP connection signs the user in through Microsoft Entra ID and gets an access token
   **for the gateway's API, issued to that agent's client app**, with the `Tools.Read` scope.
3. The agent calls the MCP server for the tool's domain in API Management. There is one server for each
   business domain (`directory`, `finance`). A server rejects tokens issued to any agent that doesn't use
   it, and lists its tools to those that do.
4. API Management maps the tool to a REST operation and applies the API policy: the token, the
   agent's allow-list, any app role, the parameters, the rate limit, and the audit record. The same
   policy applies if anyone calls the REST API directly.
5. The backend API exchanges the token **on behalf of the user** and calls the system as them, or, for
   an app-only tool, calls it as its own managed identity.

| Term | Meaning here |
|---|---|
| **Copilot Studio** | Power Platform's product for building agents (not the Microsoft 365 Copilot chat app) |
| **MCP** | [Model Context Protocol](https://modelcontextprotocol.io/): how an agent lists and calls tools |
| **The gateway** | The Azure API Management instance |
| **The backend API** | An API behind the gateway. Here, two Azure Functions apps standing in for Contoso's internal systems: one serves the directory and finance, the other budgeting |
| **Delegated access** | The system sees the user, so the user's own permissions apply |
| **App-only access** | The system sees the backend API's own identity; something else (here the gateway) must decide who may use the tool |

[docs/concepts.md](docs/concepts.md) explains these from the beginning.

## What has been tested

| Surface | Result |
|---|---|
| Scripted tests against a public gateway (the rapid profile) | Pass: per-agent tool lists and allow-lists, cross-agent refusal, both access models, no client secret anywhere, parameter validation, forged tokens, load and rate limit, the database refusing a user |
| Scripted tests over the private network (the secure profile) | Pass, including the two bypass attempts: the REST API called directly, and the backend API called directly |
| Real Copilot Studio agents (Standard harness, an earlier build) over Power Platform Virtual Network support | Pass: both access models, connector authenticated by a managed identity, data policy enforcement, a published Standard harness agent with a scheduled trigger, fault injection, an alert email arriving |
| Copilot Studio on the rapid (public) gateway, Microsoft Copilot harness | Pass: the Finance Assistant with two managed-identity connectors (directory and finance) used all five tools in Preview, including a forecast update with no approval step. Probes: identity spoofing, invalid parameters, prompt disclosure, injected instructions in a tool result and a stopped backend were all handled; "everything since 2020" was split into seven calls instead of refused. Evidence screenshots are kept in [docs/images/testing](docs/images/testing/) |
| Not tested | A second user; an unattended (scheduled or event-triggered) Microsoft Copilot harness agent (no Triggers section in the editor; the workflow route is blocked by the data policy until the Agents connector is allowed); Copilot Studio Evaluate, which would not load; the secure profile with the Microsoft Copilot harness; response size limits; content safety. The full list is in [docs/testing.md](docs/testing.md#evidence-gaps) |

**Who it's for:** platform, security, network and Power Platform teams, and architects, deciding
whether and how to give Copilot Studio agents governed access to internal systems.

**What it isn't:** production-ready (it uses the cheapest tiers that show each capability, and
test-grade shortcuts), a supported product or module, or a real backend. Copy and adapt what you need.

## Two deployment profiles

One Terraform module ([infra/modules/contoso-gateway](infra/modules/contoso-gateway/)), two thin
configurations, each with its own state:

| | `secure` (the design) | `rapid` (for development) |
|---|---|---|
| Network | Private throughout: API Management in internal virtual network mode, private endpoints, Power Platform Virtual Network support, a point-to-site VPN for administrators | Public endpoints with Microsoft Entra authentication |
| Identity, allow-lists, validation, rate limits, logs | Yes | Identical |
| Build time | About an hour | About 11 minutes |
| Use it for | Anything you want to rely on | Iterating on tools, policies and identity |

The rapid profile can't reveal faults in the private path (private DNS, the delay after linking the
enterprise policy, delegated subnets), so a change is proven only on `secure`.

## Deploy

You need a work account for makers, Copilot Studio, administrator rights and, for the secure profile,
**E5-class licences** for Power Platform Virtual Network support
([prerequisites](docs/deploy.md#prerequisites)). The secure profile costs about US$135 a month in
Australia East, or US$275 with the VPN gateway ([breakdown](docs/architecture.md#cost-of-this-demonstration)).

```bash
export ARM_SUBSCRIPTION_ID=<subscription id>
PROFILE=secure                               # or rapid
P=infra/profiles/$PROFILE
cp $P/terraform.tfvars.example $P/terraform.tfvars   # set maker_upn (rapid: also sql_firewall_ip_addresses)
az login                                     # Terraform uses this for Azure, Entra and Power Platform
terraform -chdir=$P init
terraform -chdir=$P apply -parallelism=1     # first apply: concurrent MCP tool writes fail with a 412
```

Next, deploy the backend code and load the data. In the secure profile the backends accept traffic from
the gateway only, so open a deployment window over the VPN first:

```bash
terraform -chdir=$P apply -var allow_vpn_to_backends=true   # secure only
scripts/vpn.sh setup && scripts/vpn.sh up                   # secure only

scripts/deploy-function.sh $PROFILE                 # finance + budgeting Function apps
uv run scripts/sql-setup.py --profile $PROFILE      # finance data, and access for the backend API and Finance Readers
uv run scripts/sql-setup-budgeting.py --profile $PROFILE  # budgeting data, and access for Budget Editors

terraform -chdir=$P apply -var allow_test_sign_in=true      # test window: smoke.py signs in as the agents
uv run scripts/smoke.py --profile $PROFILE
terraform -chdir=$P apply                                   # close the windows again
```

A maker then builds the agents in Copilot Studio, and Terraform trusts their connectors
([add-mcp-tool-to-agent.md](docs/add-mcp-tool-to-agent.md)). The full sequence is in
[Stand up the stack](docs/deploy.md#stand-up-the-stack), and teardown has its own order
([Teardown](docs/deploy.md#teardown)).

## What to lift out

If you already run API Management, three parts transfer. None has been tried on an existing estate.

1. The API policy ([api-policy.xml.tftpl](infra/modules/contoso-gateway/policies/api-policy.xml.tftpl)):
   validate the token, check the per-agent allow-list, require an app role for app-only tools, validate
   parameters, rate-limit per agent and user, write the audit record.
2. The MCP server pattern ([gateway.tf](infra/modules/contoso-gateway/gateway.tf)): one MCP server per
   business domain, one tool per REST operation, and a per-agent allow-list, so each tool is defined once
   and an agent only ever calls its own tools.
3. The Power Platform side: a data policy that works as an allow-list
   ([governance.tf](infra/modules/contoso-gateway/governance.tf)), and connectors authenticated by a
   managed identity with a federated identity credential and no secret.

Four parts don't transfer: the lab network, the Developer tier, the VPN and DNS forwarder, and the demo
backend.

## Documentation

| Page | Read it for |
|---|---|
| [concepts.md](docs/concepts.md) | The vocabulary: MCP, API Management as an MCP server, tokens, the on-behalf-of flow, managed identities, Power Platform environments and policies |
| [architecture.md](docs/architecture.md) | Components, a tool call step by step, delegated versus app-only access, design decisions, the two profiles, cost |
| [security.md](docs/security.md) | The threat model and every control, with its evidence |
| [governance.md](docs/governance.md) | Who approves what, the data policy, data residency, stopping an agent |
| [observability.md](docs/observability.md) | Signals, queries and alerts |
| [ai-safety.md](docs/ai-safety.md) | Prompt injection, tool design, silent failure, human oversight, the write tool |
| [networking.md](docs/networking.md) | The private network, Power Platform Virtual Network support, DNS, egress |
| [testing.md](docs/testing.md) | How to test, the results, how to evaluate an agent, and what has not been tested |
| [deploy.md](docs/deploy.md) | Prerequisites, the stand-up sequence, and teardown |
| [add-mcp-tool-to-agent.md](docs/add-mcp-tool-to-agent.md) | Step by step: connect a Copilot Studio agent to its MCP server |
| [operate.md](docs/operate.md) | Adding tools, agents and users; from what the agent shows to the layer at fault |
| [going-further.md](docs/going-further.md) | Decisions and limits before building on this; agents without a user; Microsoft's AI gateway offerings |

AI coding agents setting the project up should also read [AGENTS.md](AGENTS.md).

## Checks before you commit

```bash
uvx pre-commit install            # once: runs the hooks on every commit
uvx pre-commit run --all-files    # or run them on everything now
python3 scripts/check-docs.py     # links and anchors in the Markdown
```

The hooks scan for secrets (gitleaks), lint and format the Python (ruff), and format the Terraform.
CI runs the same checks, plus `terraform validate` for both profiles.

## Licence

[MIT](LICENSE). The Microsoft icons in [docs/diagrams/icons](docs/diagrams/icons/NOTICE.md) are not covered
by it; they remain Microsoft's, used under Microsoft's icon terms. To report a security issue, see
[SECURITY.md](SECURITY.md).
