# Observability

How to see what agents are doing, for whom, and whether they are staying inside their limits.
Everything lands in **one Log Analytics workspace**, so a tool call can be followed across layers.
Who decides and who reviews is in [governance.md](governance.md).

> Queries marked ✅ were run against a live deployment and returned what they describe. Those marked
> 🔲 are written to the documented schema and not yet run.

**The answer to "which agent read this, for whom?"** is the API policy's audit trace: one row per tool
call with the agent's client app, the user's object ID, the operation and the decision. It is written
by the gateway, so neither the agent nor the model can alter or omit it.

## Signals

| Layer | What's recorded | Where | Configured in |
|---|---|---|---|
| **Copilot Studio** | The agent's turns (`BotMessageReceived`, `BotMessageSend`, topics) with the user and conversation, and one **dependency per MCP request** named after the MCP server, with duration and success. **Not** the tool name or arguments | Application Insights `customEvents` / `dependencies` (`AppEvents`, `AppDependencies`), role `Microsoft Copilot Studio` | Per agent: Settings → Advanced → Application Insights ([below](#copilot-studio-telemetry)) |
| **API Management (requests)** | Every MCP request: `tools/list` or `tools/call`, tool name, MCP session, client, latency, errors | Application Insights `requests` | [observability.tf](../infra/modules/contoso-gateway/observability.tf) |
| **API Management (authorisation)** | One trace per tool call: **agent** (`azp`), **user** (`oid`), operation, **allowed or denied** | Application Insights `traces` | API policy `<trace>` ([api-policy.xml.tftpl](../infra/modules/contoso-gateway/policies/api-policy.xml.tftpl)) |
| **API Management (gateway)** | Every request with status, backend status, timings and **caller IP** | `ApiManagementGatewayLogs` | [observability.tf](../infra/modules/contoso-gateway/observability.tf) |
| **API Management (MCP)** | One row per MCP message: server, method, tool, client name (on `initialize`), transport, protocol version | `ApiManagementGatewayMCPLog` | Same diagnostic setting (`allLogs`) |
| **Backend** | Requests and failures of the backend API | Application Insights `requests`, `exceptions` | Function app settings |
| **Network** (secure profile) | Allowed and denied flows per subnet, including attempts to reach private endpoints | `NTANetAnalytics` (Traffic Analytics) | Virtual network flow logs |
| **Microsoft Entra ID** | Sign-ins (users, OBO exchanges, connectors' managed identities), app and consent changes, **every Microsoft Graph call with its source IP** | `SigninLogs`, `AADNonInteractiveUserSignInLogs`, `AADManagedIdentitySignInLogs`, `AuditLogs`, `MicrosoftGraphActivityLogs` | Tenant diagnostic setting |
| **Power Platform** | Changes to agents and connectors (Dataverse audit), maker and admin activity | Dataverse audit, Microsoft Purview audit | Power Platform admin center → environment → Settings → Audit (the environment owner: Terraform's identity isn't a Dataverse user there); Purview |

### What is recorded, and what is not

- **Not recorded, deliberately:** request and response **bodies**, so tool results aren't in the logs.
  API Management body logging is set to 0 bytes.
- **Tool arguments, unresolved:** every tool passes its parameters in the query string. An earlier
  test indicated that the gateway log (`ApiManagementGatewayLogs`) stored the full URL, which would put
  the dates, categories and forecast amounts in the workspace. On the rapid profile (Basic v2) none of 670
  gateway rows, and none of the backend's request rows, carried a query string. The audit trace never
  contains them. Until the secure profile is checked, treat the workspace as possibly holding tool
  arguments, restrict who can read it, and don't put sensitive values in query parameters for a tool you add.
- Copilot Studio conversation transcripts contain both arguments and results
  ([ai-safety.md](ai-safety.md#what-is-retained)).

**Watch out:** on-behalf-of sign-ins in Entra ID record the **original user's IP address**, not the
backend's. Use `MicrosoftGraphActivityLogs` to see where a Graph call actually came from.

## Review and monitor agents

### Activity: who used which tool, through which agent ✅

```kusto
AppTraces
| where isnotempty(Properties.decision)   // the API policy's audit trace
| extend agent = tostring(Properties.agent_app_id), user = tostring(Properties.user_oid),
         operation = tostring(Properties.operation), decision = tostring(Properties.decision)
| summarize calls = count() by agent, operation, decision, bin(TimeGenerated, 1h)
| order by TimeGenerated desc
```

Map `agent` (an app ID) to the agent's name with `terraform -chdir=infra/profiles/secure output agents`.

### Denials: agents probing tools they aren't allowed ✅

```kusto
AppTraces
| where Properties.decision == "denied"
| summarize denials = count() by agent = tostring(Properties.agent_app_id),
            operation = tostring(Properties.operation), user = tostring(Properties.user_oid)
| order by denials desc
```

### Performance: latency and errors per MCP tool ✅

```kusto
AppRequests
| where Properties["api.type"] == "mcp-backend" and Properties["gen_ai.operation.name"] == "tools/call"
| summarize calls = count(), failures = countif(Success == false),
            p50 = percentile(DurationMs, 50), p95 = percentile(DurationMs, 95)
          by server = extract(@"/([^/]+)/mcp", 1, Name), tool = tostring(Properties["gen_ai.tool.name"])
```

**Caveat, observed here:** when API Management throttles or refuses a tool call *inside* the MCP
server, the client still gets HTTP 200 with the error as the tool's text (`{"statusCode": 429,
"message": "Rate limit is exceeded..."}`), so `AppRequests` counts it as a success. Measure
throttling and denials from `ApiManagementGatewayLogs` or the audit trace, not from this
query's `failures`.

### MCP traffic by server, client and tool ✅

```kusto
ApiManagementGatewayMCPLog
| summarize calls = count(), errors = countif(isnotempty(Error))
          by McpServerEndpoint, ClientName, Method, ToolName
| sort by calls desc
```

`ClientName` is only filled on `initialize`. The Microsoft Copilot harness appears as `McpToolsListClient` (when it lists tools) and `AgenticLoop` (when it calls them), `mcp` is the Python SDK and `smoke` the smoke test. `Error`
stays empty when a client asks for a tool its server doesn't have, so count denials from the
audit trace above, not from here.

### Network path: which subnet the agent's calls came from ✅

```kusto
ApiManagementGatewayLogs
| where ApiId endswith "-mcp"
| summarize calls = count() by ApiId, CallerIpAddress
```

Copilot Studio's calls arrive from the Power Platform delegated subnets (here `10.41.1.x`, the
Australia Southeast one); `10.255.201.x` is the test VPN.

### Throttling: who's hitting the rate limit ✅

```kusto
ApiManagementGatewayLogs
| where ResponseCode == 429
| summarize throttled = count() by ApiId, bin(TimeGenerated, 5m)
```

Throttled MCP tool calls show here under the REST API (`internal-systems`), not the MCP server: the MCP
server calls the API internally, and the rate limit is in the API's policy. Gateway logs arrive
5–15 minutes after the call.

### The agent's view: tool calls from Copilot Studio ✅ (needs the agent's telemetry turned on, below)

```kusto
// Copilot Studio's side: one dependency row per MCP message to the server (named after the MCP server)
AppDependencies
| where AppRoleName == "Microsoft Copilot Studio"
| project TimeGenerated, server = Name, DurationMs, Success, ResultCode,
          conversation = tostring(Properties.conversationId), channel = tostring(Properties.channelId)

// Join key to API Management: the user. Copilot Studio's events carry the user's object ID in fromId,
// and API Management's audit trace carries the same ID as user_oid.
AppEvents
| where AppRoleName == "Microsoft Copilot Studio" and Name == "BotMessageReceived"
| project TimeGenerated, user = tostring(Properties.fromId), conversation = tostring(Properties.conversationId)
```

What Copilot Studio records here is the agent's turns (`BotMessageReceived`/`Send`, `TopicStart`...)
and one dependency per MCP request, with duration and status. It does **not** record the tool's name
or arguments (they would be in the sensitive properties, which are off). So the full picture of one
tool call is: Copilot Studio (who, which conversation, how long) + API Management trace (which
agent app, which tool, allowed or denied) + gateway logs (caller IP). Correlate on user ID and time.

### Silent failure: tool calls that failed

When an agent can't reach a tool, the user sees a fluent answer and the gateway sees nothing
([ai-safety.md](ai-safety.md#silent-failure) has the diagram and the observed cases). The only record is
on Copilot Studio's side:

```kusto
AppDependencies
| where AppRoleName == "Microsoft Copilot Studio" and Success == false
| project TimeGenerated, server = Name, ResultCode, conversation = tostring(Properties.conversationId)
```

When a connection drops to "Reconnect" the agent doesn't show an error: it answers from general
knowledge, and the user sees a plausible reply with no tool behind it. The failure **is** recorded
here (checked against a real occurrence), but nothing alerts on it yet ([Alerts](#alerts)). A conversation
with no tool call at all isn't a failure by itself (chit-chat has none), so detecting absence needs a
rule per agent. Join Evaluate / Preview runs to the gateway as in [testing.md](testing.md#join-quality-to-the-gateway).

### Identity: on-behalf-of exchanges and Graph calls ✅

The tables were populated within an hour of the calls on the rapid profile. An earlier deployment lost
them, and the cause was not found ([what is not observed](#what-is-not-observed)).

```kusto
// Which users the backend API acted for, and against which downstream resource
AADNonInteractiveUserSignInLogs
| where AppId == "<api_client_id>"
| summarize count() by UserPrincipalName, ResourceDisplayName, ResultType

// Where the API's Graph calls came from (should be the NAT gateway or firewall IP)
MicrosoftGraphActivityLogs
| where AppId == "<api_client_id>"
| summarize count() by IPAddress, RequestUri
```

### Network: attempts to bypass API Management ✅ (detect from the source side)

Anything reaching the backends' private endpoints from somewhere other than API Management's
subnet is a bypass attempt (or a deliberate deploy window):

```kusto
NTANetAnalytics
| where FlowStatus == "Allowed" and DestIp in ("<function endpoint IP>", "<SQL endpoint IP>")
| where not(SrcIp startswith "10.40.1.")      // API Management's subnet
| summarize flows = count(), earliest = min(TimeGenerated) by SrcIp, DestIp, DestPort
```

Tested: calls from a VPN client straight to the backend API (443) and SQL (1433) private endpoints
**time out**, so the block works ([smoke test check 8](testing.md#3-smoke-test)), and these queries find
the attempts. **The surprise:** the log shows them as **Allowed**, from the VPN client's side, and
records **no denied flow** at the private endpoint. Don't build an alert on `FlowStatus == "Denied"`
for this. Values are `Allowed` and `Denied`, not letters. The only `Denied` rows seen are internet
scanners hitting API Management's management ports, refused by the default deny rule.

### Parameters the gateway rejected ✅

A spending query with a bad category, a date range the wrong way round or longer than 12 months is
refused by the gateway with a 400 before it reaches the backend. Like a role denial, it is in the
gateway log, not the audit trace:

```kusto
ApiManagementGatewayLogs
| where ResponseCode == 400 and Url has "finance/spend"
| project TimeGenerated, CallerIpAddress, Url, BackendResponseCode
```

`BackendResponseCode` is empty when the gateway refused the call itself.

### App-only tool: role denials and the managed identity ✅

A user without the app role is refused by the gateway with a 403 that is **not** in the authorisation
trace. Find it in the gateway log, and see the backend API's identity sign in to Azure SQL:

```kusto
ApiManagementGatewayLogs
| where ResponseCode == 403 and Url has "cost-centres"
| project TimeGenerated, CallerIpAddress, ResponseCode, LastErrorReason, LastErrorMessage

AADManagedIdentitySignInLogs
| where TimeGenerated > ago(1h)
| take 20
```

The second shows the managed identity (for the app-only tool and for the on-behalf-of exchange's
assertion) signing in; it does not name the user, because no user is involved.

## Copilot Studio telemetry

Turn on per agent: **Settings → Advanced → Application Insights**, paste the workspace-based
Application Insights **connection string**, and **Save**. Leave *Log sensitive properties* off (it
records message text). **Publish** afterwards: events from chats in the test pane arrive too
(`DesignMode = True`), but publishing is what the setting is documented to need, and the agent needs
a channel to publish (this demonstration adds Teams only, not made available in the Microsoft 365
Copilot agent store). The connection string is a write-only ingestion key, entered by the maker in the portal. Get it with:

```bash
az monitor app-insights component show -g <resource group> -a <app insights name> --query connectionString -o tsv
```

It lands in `AppDependencies` / `AppTraces` / `customEvents` in the same workspace as everything
else, so the agent's turn and the API Management trace can be read side by side. The data policy
keeps the *Application Insights in Copilot Studio* connector in the Business group for this.

## Alerts

| Alert | Fires when | Means |
|---|---|---|
| `<prefix>-authz-denial-spike` | More than 20 401/403 responses in 15 minutes, per API | An agent or token probing tools it isn't allowed, or a broken connection |
| `<prefix>-backend-errors` | More than 5 backend 5xx in 15 minutes | The backend API or Graph/SQL failing |

Both are defined in [observability.tf](../infra/modules/contoso-gateway/observability.tf). Set `alert_email` and they use an
action group that emails that address; without it **nobody is notified**.

- ✅ `authz-denial-spike` fired on a burst of 60 unauthenticated calls, five minutes later, and its
  email arrived. 🔲 `backend-errors` has never fired.
- **The email address must be verified.** Azure Monitor sends a confirmation email, and until it is
  accepted nothing is delivered, although the receiver shows as enabled.
- A stopped backend API returns 403, which counts towards `authz-denial-spike`, so that alert also
  fires for an outage ([operate.md](operate.md#troubleshooting-from-symptom-to-layer)).
- ⏳ No alert yet for a failed Copilot Studio tool call, which is the one most worth building.

## What is not observed

| Gap | Effect |
|---|---|
| **Microsoft Entra logs have been unreliable** | They arrived on the latest deployment and were lost on an earlier one; the cause was not found. Check the tables are filling after every deployment, and read the identity side in the Microsoft Entra admin center if they are not |
| **Tool names and arguments aren't in Copilot Studio's telemetry** | Deliberate: they would be in the sensitive properties, which are off. Correlate with the gateway's trace on the user's object ID and time |
| **A role denial and a rejected parameter aren't in the audit trace** | They are separate policy steps. Find them in the gateway log (queries above) |
| **Nothing alerts on a failed or absent tool call** | The failure most likely to mislead a user leaves no row at the gateway ([ai-safety.md](ai-safety.md#silent-failure)) |
| **Changes to agents** | Dataverse auditing isn't turned on ([governance.md](governance.md#known-governance-gaps)) |
| **A blocked bypass attempt shows as Allowed** | Flow logs record it from the source side; alert on the source, not on a denied flow |

## Learn more

- [Evals](testing.md#testing-the-agent-evals): quality scores must join to these traces, or silent failure looks like a win
- [Monitor MCP server traffic in API Management](https://learn.microsoft.com/azure/api-management/monitor-mcp-servers)
- [Copilot Studio telemetry with Application Insights](https://learn.microsoft.com/microsoft-copilot-studio/telemetry-overview)
- [Environment-level telemetry (preview)](https://learn.microsoft.com/microsoft-copilot-studio/advanced-environment-level-agent-telemetry)
- [Microsoft Graph activity logs](https://learn.microsoft.com/graph/microsoft-graph-activity-logs-overview)
- [virtual network flow logs](https://learn.microsoft.com/azure/network-watcher/vnet-flow-logs-overview)
- [Copilot Studio security and governance](https://learn.microsoft.com/microsoft-copilot-studio/security-and-governance)
- [Monitor operations, compliance and capacity](https://learn.microsoft.com/microsoft-copilot-studio/guidance/sec-gov-phase5)
