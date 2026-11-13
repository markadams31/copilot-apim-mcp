# Operate

Day-two tasks for a running deployment: who gets which tools, adding tools, agents and backends,
managing user access, and finding the layer at fault when something fails. Removing a deployment is in
[Teardown](deploy.md#teardown).

## Tools, servers and agents

Two Terraform maps in [main.tf](../infra/modules/contoso-gateway/main.tf) decide who gets which tools:

- `server_definitions` lists the tools on each MCP server. There is one server for each business domain.
- `agent_definitions` lists the servers each agent uses.

An agent's tools are the union of its servers' tools. Terraform generates the MCP servers and the
allow-list from the two maps.

```hcl
locals {
  server_definitions = {
    directory = { tools = ["directory_get_my_profile"] }
    finance = {
      tools = [
        "finance_list_cost_centres",
        "finance_query_spend",
        "budgeting_get_forecast",
        "budgeting_update_cost_centre_forecast",
      ]
    }
  }

  agent_definitions = {
    employee-assistant = { display_name = "Contoso Employee Assistant", servers = ["directory"] }
    finance-assistant  = { display_name = "Contoso Finance Assistant", servers = ["directory", "finance"] }
  }
}
```

**Treat every change to these maps as an access grant.** Putting a tool on a server grants it to every
agent that uses the server, and adding a server to an agent grants all of that server's tools. Either
lets the agent read that data on behalf of any user who uses it, so review the change like any other
permission change ([governance.md](governance.md)).

### Give an agent a tool

1. Add the server that lists the tool to the agent's `servers`. To reach this agent only, put the tool
   on a server that only this agent uses: a server lists all its tools to all its agents.
2. Run `terraform plan`. Expect an in-place change to `azurerm_api_management_api_policy.tools` (the
   allow-list gains `<tool>|<agent app ID>`) and, for a new server, that server's policy.
3. Apply with `-parallelism=1`, because concurrent writes to MCP tools fail with a 412. Then run the
   smoke test. An agent that gains a new server also needs a connector for it
   ([add-mcp-tool-to-agent.md](add-mcp-tool-to-agent.md)).

### Add a tool (a new REST operation)

1. Implement the route in the backend (here, [function_app.py](../backend/function_app.py)). If it reads
   data, choose the access model first ([architecture.md](architecture.md#access-models-delegated-and-app-only)).
   The default is delegated access: call `_obo(req, "<downstream scope>")` and use that token. Use the
   app's own identity only where users have no direct access and the gateway adds its own check
   ([security.md](security.md#4-delegated-access-by-default-app-only-access-only-with-its-own-controls)).
2. Add the operation to [openapi.yaml](../backend/openapi.yaml) with an `operationId` (this becomes the
   tool name) and a careful `description`. **The model reads the description to decide when to call the
   tool.** Say what the tool returns and when to use it, and don't put instructions in it.
3. If the tool needs a new downstream permission, add it to the API app's `required_resource_access`
   and grant admin consent (`azuread_service_principal_delegated_permission_grant`).
4. Add the operation ID to the `tools` of the server for its domain, or to a new server. Every agent that
   uses that server may then call it. A tool on no server is denied to everyone.
5. Plan and apply, deploy the backend code, and run the smoke test. Add a smoke test check for the new
   tool.

Guidelines for good tools:

- **Read-only by default** (`GET`). A write tool needs its own risk review and a way for a human to
  approve the change ([ai-safety.md](ai-safety.md#human-oversight)).
- **Narrow, not "run any query".** The model uses whatever latitude it is given. A tool with
  parameters, like `finance_query_spend`, takes **typed** parameters (a fixed list of values, dates
  with a maximum range) and runs one fixed, parameterised statement, so the model never writes the
  query. Describe the parameters in the OpenAPI file so the gateway can validate them
  (`validate-parameters`) and the agent knows what to send.
- **Make every query parameter required.** API Management's import puts required query parameters in
  the operation's URL template, and its MCP layer then appends optional ones with a second `?`, which
  corrupts the request. Use an explicit value such as `all` instead of an optional parameter.
- **Return small responses.** Return what answers the question, not whole tables.
- **Keep names stable.** Agents and prompts come to depend on them.
- **Name tools for the task**, as `<system>_<action>` (`finance_query_spend`), and state the access
  model in the description, not the name ([architecture.md](architecture.md#the-tools)).

### Add an app-only tool

1. Add the operation to [openapi.yaml](../backend/openapi.yaml) and the route to
   [function_app.py](../backend/function_app.py). The route reads as `_managed_identity` and never calls
   `_obo`, and it returns which identity read the data, as `finance_list_cost_centres` does.
2. Give the backend API's identity the narrowest access the data source allows. For SQL, that is a view
   and a `SELECT` on it, as in [sql-setup.py](../scripts/sql-setup.py).
3. Define an app role on the API app in [identity.tf](../infra/modules/contoso-gateway/identity.tf) and
   add the tool to `tool_roles` in [main.tf](../infra/modules/contoso-gateway/main.tf), so the gateway
   requires the role.
4. Put the tool on a server, and get the data owner's agreement: users will see data they couldn't
   reach themselves ([architecture.md](architecture.md#access-models-delegated-and-app-only)).

### Onboard an agent

1. Add an entry to `agent_definitions` listing the servers it uses.
2. Apply. Terraform creates the agent's Entra app, pre-authorises it for `Tools.Read`, adds the app to
   the policy of each server the agent uses, and extends the allow-list.
3. Give the agent's maker its client ID and the URL of each server it uses
   (`terraform -chdir=infra/profiles/<profile> output agents`). The maker follows
   [Stand up the stack](deploy.md#stand-up-the-stack) steps 4 to 7 and
   [add-mcp-tool-to-agent.md](add-mcp-tool-to-agent.md), once for each server.
4. Trust each connector. There is no client secret: a connector authenticates with a managed identity,
   which you trust by adding one `copilot_connectors` entry for each connector (all naming the same
   agent) and applying again.
5. In production, turn on "Assignment required" for the agent's enterprise application and assign the
   users or groups who may use it.

### Add a backend API

The repository has two: `internal-systems` (finance and directory) and `budgeting`. To add another:

1. Import its OpenAPI spec as another `azurerm_api_management_api`. Supply the spec inline or from a
   public URL, because an internal-mode API Management can't fetch a spec from a private URL.
2. Give it the same kind of API policy: token validation plus a generated allow-list. Reuse
   [api-policy.xml.tftpl](../infra/modules/contoso-gateway/policies/api-policy.xml.tftpl).
3. Make the backend reachable **only from API Management's subnet**, through a private endpoint (PaaS)
   or network security group rules (VMs, or on-premises over VPN or ExpressRoute).
4. Decide how the backend authenticates the user:

   | The backend can... | Do this |
   |---|---|
   | Validate Entra tokens | Forward the user's token. If the backend needs its own audience, add an on-behalf-of hop, as the backend API does |
   | Only use its own API key or service account (app-only access) | Have API Management authenticate with its managed identity (preferred) or a Key Vault secret, **and** pass the user's identity (for example `oid`) in a header that the backend logs and enforces. This is weaker than on-behalf-of: the backend must be trusted to apply per-user permissions |

5. Register each new `operationId` in `local.tool_api` in [main.tf](../infra/modules/contoso-gateway/main.tf),
   so the MCP tools point at the right API Management API, and put the tools on a server. Tool resource
   names must be unique across the whole API Management instance
   (see [AGENTS.md](../AGENTS.md#api-management-behaviour-worth-knowing)).

### Make a change safely

| Change | How long it took here | Check afterwards |
|---|---|---|
| Add or remove a tool for an agent | One `terraform apply -parallelism=1`: **about 95 seconds**, in effect for the next chat. A removed tool made the agent say it **couldn't verify** the answer, with no error, so a removal reads as an unhelpful agent, not a block | `uv run scripts/smoke.py` (needs the [test sign-in window](testing.md)) |
| Add an agent | Apply, then the maker steps | [add-mcp-tool-to-agent.md](add-mcp-tool-to-agent.md) |
| Stop an agent | [The levers](governance.md#stopping-an-agent-and-revoking-access) | Chat as that agent and expect a refusal |

Run the smoke test after any change. It plays the agent's part with a real sign-in, so it catches what
a plan can't.

## User access

Who may use a tool is decided by the system behind it (delegated tools) or by an app role at the gateway
(app-only tools), not by the agent.

### Give a user access to spending (delegated tool)

The database authorises the user, not the agent. For `finance_query_spend` it grants `SELECT` on the
spend view to one Entra group, Contoso Finance Readers, so access is a group membership, not a
database change:

- Terraform manages the group's members through `finance_reader_upns` (default: the maker). List the
  users in `infra/profiles/<profile>/terraform.tfvars` and apply.
- [sql-setup.py](../scripts/sql-setup.py) creates the group's database user and the grant, once. The
  equivalent SQL is:

  ```sql
  CREATE USER [Contoso Finance Readers (contoso)] FROM EXTERNAL PROVIDER;
  GRANT SELECT ON OBJECT::finance.v_spend TO [Contoso Finance Readers (contoso)];
  ```

A membership change takes effect at the user's next sign-in, when their token is reissued. Removing the
group's database user (`sql-setup.py --revoke-readers`) takes effect at once, which is how the
demonstration shows the database refusing.

No user gets access to the cost-centres view. Only the app-only tool serves that data, so the
gateway's role check decides who sees it.

### Give a user access to budgeting forecasts (delegated read and write)

Budgeting is a **separate** Contoso system, with its own Function app, API Management API and SQL
database. Access to forecasts is membership of Contoso Budget Editors, managed through
`budget_editor_upns` (default: the maker). [sql-setup-budgeting.py](../scripts/sql-setup-budgeting.py)
creates the group's database user and grants `SELECT` on the forecast view plus `EXECUTE` on
`budgeting.set_forecast`. Cost-centre codes are duplicated in that database, with no foreign key to
finance. `--revoke-editors` drops the grant for the refusal demonstration.

The write tool `budgeting_update_cost_centre_forecast` has **no approval gate** in this proof of
concept ([ai-safety.md](ai-safety.md#human-oversight)).

### Give a user an app role (app-only tools)

An app-only tool reads as the backend API's own identity, so the database can't tell users apart and the
gateway decides instead: the user's token must carry the tool's app role. Terraform assigns
`CostCentres.Read` to `cost_centres_user_upns` (default: the maker). To add a user, list them in
`infra/profiles/<profile>/terraform.tfvars` and apply:

```hcl
cost_centres_user_upns = ["maker@contoso.com", "someone@contoso.com"]
```

Removing a user takes effect when their access token next refreshes, not at once. Assigning the role to
a **group** needs Entra ID P1; direct user assignment, as used here, does not.

## Troubleshooting: from symptom to layer

Start from what the **agent or user sees**, find the layer, then look in the one place that layer
reports. The queries are in [observability.md](observability.md), and the sign-in and token concepts are
in [concepts.md](concepts.md#tokens-scopes-and-claims).

### The one idea that saves time

A tool call crosses five layers, and **most failures look the same from the chat**: the agent says it
couldn't do something, or answers from general knowledge. Copilot Studio receives every gateway refusal
as **HTTP 200 with the error as text**, so the agent's own telemetry counts refusals as successes. Find
the layer first.

| Layer | Owner | Reports in |
|---|---|---|
| 1. Connection (the user's sign-in on the connector) | Maker, Power Platform | Power Apps → Connections; the chat's "Connect to continue" card |
| 2. Policy and network (data policy, delegated subnets, DNS) | Power Platform admin, network | Chat error text; no row in API Management |
| 3. Gateway (token, agent, allow-list, rate limit) | API Management owner | `ApiManagementGatewayLogs`, the audit trace |
| 4. Backend (the backend API, on-behalf-of) | API owner | Functions app logs in Application Insights |
| 5. Data (Graph, SQL permissions) | Data owner | The tool's own text; SQL's database users |

### Symptom table

| What the agent or user sees | Layer | Check first | Fix |
|---|---|---|---|
| Answers from general knowledge, never calls the tool; **no row at all in API Management** | 1 or 2 | Power Apps → Connections: is it "Reconnect"? If it says Connected, check the private DNS links and delegated subnets (the DNS fault described below) | Reconnect: delete the connection, create a new one, then **Allow** in the chat ([steps](add-mcp-tool-to-agent.md#troubleshooting)). DNS: restore the link, then allow about 6 minutes |
| Sign-in fails with `AADSTS70025` | 1 | The app's federated identity credential exists and its subject matches the connector's exactly | Fix `copilot_connectors`, apply |
| Sign-in fails with `AADSTS50011` | 1 | The connector's redirect URL is on the agent's app registration | Fix `copilot_connectors`, apply |
| `DataLossPreventionViolation` | 2 | The environment's data policy ([governance.tf](../infra/modules/contoso-gateway/governance.tf)) | Remove the blocked connector or knowledge source, or change the policy through review |
| Adding the server times out, or the tool list won't load | 2 | Was the enterprise policy linked more than 30 minutes ago? Delegated subnets resolve and reach API Management? | [networking.md](networking.md) |
| "Validation Failed" or **401** | 3 | The connector's client ID belongs to an agent that uses this server; token audience and tenant | Use the client ID of an agent that uses this server |
| **403** naming the tool, in the audit trace as a denial | 3 | Is this tool on a server this agent uses (`agent_definitions`, `server_definitions`)? | This is an access grant, so review the change ([tools, servers and agents](#tools-servers-and-agents)) |
| **"hit a rate limit"** (429) | 3 | The throttling query | Wait a minute; raise the limit only deliberately |
| **403 Forbidden** and the audit trace shows the call was **allowed** | 4 | Is the backend API running? | See below: a stopped backend looks like a denial |
| **403** with "This user is not assigned the role for this tool" | 3 | The user holds the app role (`cost_centres_user_upns`), and signed in after it was assigned: an older token lacks it | Assign the role, then have the user reconnect or wait for the token to refresh. Not in the audit trace: look in `ApiManagementGatewayLogs` |
| `obo_failed` (502) naming `AADSTS70021` or `AADSTS7000215` | 4 | The federated identity credential on the API app: its subject must be the backend API identity's principal ID. In secret mode, whether the secret expired | Fix `azuread_application_federated_identity_credential.api_obo`, or apply with a new secret |
| `app_only_connect_failed` (no database user for the identity) or `app_only_query_failed` (no `SELECT` on the view) from `finance_list_cost_centres` | 5 | Does the backend API's identity have a database user and `SELECT` on `finance.v_cost_centres`? | Run `scripts/sql-setup.py` in a deploy window |
| `database_refused` (403) from `finance_query_spend` | 5 | Is the user in Contoso Finance Readers (`finance_reader_upns`), and has `sql-setup.py` given the group its database user? A new member needs a fresh sign-in | Add them to the group through review. Azure SQL authorises the user, not the agent, so this is the control working |
| **400** from `finance_query_spend` with `"rejected_by": "gateway"`, or `invalid_category`, `invalid_dates`, `invalid_range` from the backend | 3 or 5 | The arguments: category one of travel, software, training, equipment, all; dates as YYYY-MM-DD, `from` before `to`, at most 12 months apart | Usually the model's arguments; rephrase the question. A gateway 400 isn't in the audit trace |
| `finance_query_spend` fails through MCP but works as plain REST | 3 | Was a parameter made optional in [openapi.yaml](../backend/openapi.yaml)? The MCP layer then corrupts the query string | Keep every query parameter required ([guidelines](#add-a-tool-a-new-rest-operation)) |

### Faults injected, and what they looked like

Each fault was introduced on a running deployment of the secure profile, observed and then undone, so
that whoever supports the deployment has seen the symptom before it happens for real.

| Fault | What the chat showed | What the gateway showed | Misleading because |
|---|---|---|---|
| **Backend stopped** (Function app stopped) | **"403 Forbidden"** from the tool | The MCP call itself returned 200; the REST call behind it returned **403** | An authorisation alert on 403s would fire for an outage. Tell them apart by the audit trace: a real denial has `decision` `denied`; this one is `allowed` |
| **Network rule on API Management's subnet removed** (the source range of the Power Platform subnet) | **Nothing changed**: tools kept working | No change | Azure's default rules already allow traffic from peered networks, and the rule that was removed was an *allow* with no *deny* behind it. It was never a control. The control that matters is the network security group on the private endpoint subnet, proven by [smoke test check 8](testing.md#3-smoke-test) |
| **Explicit deny added** for the Power Platform range | **Nothing changed** for at least 2 minutes | No change | Network security group rules apply to **new** connections. Power Platform reused a warm one. A rule change is not a kill switch, and you cannot test a block by changing a rule and chatting |
| **Private DNS link removed** for the second region (the network that carries Power Platform's calls) | The agent **answered anyway**, from "knowledge" and the user's account details, with no error. It looked plausible, and partly right | **No row at all**: nothing reached API Management | It is the worst kind of failure: nothing is wrong on any dashboard. It recovered about **6 minutes after** the link was restored, and one chat in between still failed. Detect it by absence: the audit trace has no calls while the agent is in use |

Turning **public-client sign-in off** on the agent apps doesn't affect the Copilot Studio connector,
which signs in as a confidential client. Revoking a user's sign-in sessions was not tested.

### Where each signal lives

- **Who called which tool, and was it allowed:** the audit trace in `ApiManagementGatewayLogs`
  ([activity and denials queries](observability.md#activity-who-used-which-tool-through-which-agent-)).
- **Which agent is it really:** the trace attributes a call to the agent whose **connector** made it
  (the token's `azp`). If a maker attaches another agent's connector, the trace names the connector's
  agent, not the one the user was chatting with. Cross-check with the Copilot Studio telemetry on the
  user's object ID ([the agent's view](observability.md#the-agents-view-tool-calls-from-copilot-studio--needs-the-agents-telemetry-turned-on-below)).
- **Failures the agent hid:** [the silent-failure query](observability.md#silent-failure-tool-calls-that-failed).
