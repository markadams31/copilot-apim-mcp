# AGENTS.md

For AI coding agents setting up, running or changing this project. People should read
[README.md](README.md) and [docs/](docs/) instead; this file is terse on purpose and records what was
learnt the hard way. Everything below was observed in one tenant (2026-11-09 to 11-13) unless it says
otherwise. Where a claim wasn't verified it's marked **(unverified)**.

## What this is

Contoso's Copilot Studio agents call internal REST APIs as MCP tools through one Azure API Management
gateway, with connectors authenticated by a managed identity (no client secret). Two profiles share one
module ([infra/modules/contoso-gateway](infra/modules/contoso-gateway/)): `infra/profiles/secure`
(private: API Management in internal mode, private endpoints, VPN, Power Platform Virtual Network support) and `infra/profiles/rapid`
(public Basic v2, SQL firewall; about 11 minutes to build). Separate state each. The design and its
reasoning are in [docs/architecture.md](docs/architecture.md). Terraform builds everything except
what only a person can do. The access
models (delegated vs app-only) in [docs/architecture.md](docs/architecture.md#access-models-delegated-and-app-only).

## Order of operations

Follow **[docs/deploy.md](docs/deploy.md#stand-up-the-stack)** end to end. Prerequisites and licences:
[docs/deploy.md](docs/deploy.md#prerequisites). Maker UI clicks:
[docs/add-mcp-tool-to-agent.md](docs/add-mcp-tool-to-agent.md). The rest of this file is footguns only.

## What an agent can and can't do

- **Can:** Terraform, `az`, Graph and admin APIs through `az rest`, scripts in `scripts/`, and driving
  the browser (Claude in Chrome) for Copilot Studio, Power Apps and the admin center.
- **Can't, and shouldn't try:** enter passwords or MFA codes, create the service account or mailbox, or
  complete payments. Sign-in popups reuse the existing browser session, so clicking **Sign in** usually
  works silently; if a password or MFA page appears, stop and hand over.
- **Warn the user before** anything that signs in, grants a role, links billing or publishes.

## Accounts and roles (a frequent time sink)

- The Power Platform admin center and Copilot Studio **reject personal Microsoft accounts**. A tenant
  owner who signs in as `#EXT#` or personal can't use them. They need a work (member) account.
- Terraform and `az` here ran as that personal/guest owner. It can read most admin APIs, but the billing
  APIs return **403 Forbidden** for it (`api.powerplatform.com`, the Terraform billing data source, and
  an environment update that touches the billing link).
- For billing plans the work account needs **Power Platform Administrator** (Entra) and **Contributor or
  Owner on the subscription**. A role on the resource group only shows the subscription as "Partial
  access", greyed out. After a role change, sign out and in again and reload.
- A `terraform apply` that "removes the billing policy" is the provider calling the 403 API; see the
  environment notes below.

## Licensing, credits and environment type

- Standard-harness agents work in the **test pane without credits**. **Publishing** needs a licence:
  Agent status says "uses premium features, upgrade to publish" (a warning once the environment is on
  pay-as-you-go). The real publish blocker was **no channel configured**.
- Published agents and every trigger firing consume Copilot Credits. Pay-as-you-go is billed per use.
  Pricing wasn't seen **(unverified)**.
- The **newer (preview) harness**, which Home offers as the **Agent** card (Learn now calls it the Microsoft Copilot harness, formerly the GitHub
  Copilot harness), is usage-billed: in an environment with no credits, Preview answers "out of
  credits" (`EnforcementUsageCredits`). With a pay-as-you-go plan linked it worked, with the same
  connector and tools as the standard harness.
- **Always create a Sandbox, never a Developer environment** (both profiles). `environment_type`
  defaults to `"Sandbox"` in the module and both profiles (changed 2026-11-12 after rapid left
  `contosodev-agents` as Developer). Developer can't take a pay-as-you-go plan or be converted
  (Learn only documents production <-> sandbox). The Microsoft Copilot harness then
  fails Preview with `EnforcementUsageCredits` / 0 credits. Link a billing plan (admin-center create
  + import; see Terraform below). Sandbox needs a Dataverse security group (Terraform makes one).
- **Pay-as-you-go supports only Production and Sandbox.** Without it, only the standard harness test
  pane works; publishing and the Copilot harness need the plan.
- The tenant had 0 MB prepaid Dataverse capacity; the plan's **Dataverse meter** covered creation.
- In the billing-plan wizard, ticking **Copilot Studio** also ticked **Windows 365 for Agents** (a
  separate paid product). Untick it.
- Unmanaged Developer environments stop working on 2026-12-15 (Learn). Prefer Sandbox regardless.

## Terraform

- First apply: `-parallelism=1`. Concurrent MCP tool writes return 412 Precondition Failed.
- Updating an `azapi_resource` MCP server, even only its description, **deletes its tools** while state
  still lists them. The server has `ignore_changes = [body]`. To change one, taint it.
- `terraform plan` always shows four cosmetic changes (two MCP policies, the API policy, Entra
  diagnostics). Expect them.
- `terraform fmt` also reformats `terraform.tfvars`, so exact-string edits to it fail. Use a regex.
- **Never chain `plan` and `apply` in one command** in an agent: the permission layer blocks it as a
  blind apply. Plan, show it, then apply the saved plan file.
- **The billing plan ID is not the Azure resource's GUID.** `Microsoft.PowerPlatform/accounts/<name>`
  has a `systemId` GUID that gives `BillingPolicy_Invalid`. The real ID appears in the imported
  environment's state (`billing_policy_id`) or the admin center's own calls.
- Creating a Sandbox with the plan from Terraform failed (the Terraform principal can't see the plan).
  Working route: create the environment in the admin center (Manage > Environments > New, Sandbox,
  Australia, Dataverse on, Pay-as-you-go on, plan picked by name, security group), then
  `terraform import module.gateway.powerplatform_environment.agents <id>`.
- After the import, the environment resource must ignore `billing_policy_id`, `dataverse` and the
  settings changed after import, or the provider tries to "add Dataverse" and "remove billing policy"
  and fails. Bing search was turned off via `PATCH .../environments/<id>` (`bingChatEnabled`).
  "Move data across regions" should also be off **(unverified)**.
- The data policy must hold connectors by **full id** (`/providers/Microsoft.PowerApps/apis/shared_...`).
  The bare name unlocks **Add trigger** after about 5 minutes but connection creation stays blocked
  ("blocked by Data Loss Prevention policy"). `allow_agent_triggers` does this for
  `shared_microsoftcopilotstudio`. Duplicate connector names exist in the list: group with `...`.
- A `copilot_connectors` entry's `subject` is exact. After **Update connector** on managed identity,
  read it from the Managed identity field (or the admin API list of custom APIs), not a truncated UI
  copy. Key = the last segment of the redirect URL (e.g. `new-5fcontoso-20finance-20tools-5f…`).
- **Replacing the environment recreates nothing for makers.** Agents and custom connectors are
  environment-scoped. A Developer→Sandbox replace (or a new Sandbox) wipes them. Create a new MCP
  connector, then **replace** the whole `copilot_connectors` entry (old key/redirect/subject will
  `AADSTS50011` / `AADSTS70025`). Applying also swaps the connector id in the data policy.

## API Management behaviour worth knowing

- **BasicV2 provisions in under 2 minutes** (classic internal mode: 45+). The whole rapid apply took
  about 11 minutes with `-parallelism=1`.
- **MCP and query parameters:** the OpenAPI import puts *required* query parameters into the operation's
  URL template; the MCP layer then appends *optional* ones with a second `?`, corrupting the request
  (`to` arrived as `2026-11-11?category=travel`). Make every query parameter of an MCP tool required.
  A request missing a templated parameter gets 404 (no matching operation), not 400.
- **Policy expressions:** `DateTime.TryParse` isn't allowed in the expression sandbox; validate the format
  with `validate-parameters` first, then use `DateTime.Parse`. Test a policy fragment by PUTting it to the
  API with `az rest`: the error names the element and member, unlike Terraform's bare "ValidationError".
  A test PUT leaves a policy behind; `terraform import` it before the next apply.
- **Rate limits are approximate** on the v2 tier: the first 429 came at call 32-33 for a limit of 30
  (classic Developer was exact). The pressure test allows a small tolerance.

## Copilot Studio / Power Apps maker wiring (hard lessons)

- **Prefer the Microsoft Copilot harness** (Home → **Agent**; formerly called the GitHub Copilot
  harness, and the portal may still say either). Gateway / connector / Terraform steps match Standard; editor and billing differ.
  Needs Sandbox + pay-as-you-go or Preview says `EnforcementUsageCredits`. **Contoso Finance
  Assistant** is Standard — do not default to it unless asked.
- **Save is required** on the Copilot harness: naming on `/agents/new` alone does not persist; Save
  (Ctrl+S) until the URL has a bot id. Agent and environment IDs die with the environment, so never
  reuse IDs from an earlier build.
- New Sandbox: the maker may need **System Administrator** ("Get role") before Create agent works.
- **MCP Add stays disabled** if the server name is already in use ("Choose a different server name").
  Cancel and **Add tool → pick the existing Contoso Finance Tools** instead of recreating. Recreate
  only when the environment is new and no connector exists yet.
- **Never create the connection from the MCP wizard** (and never before managed identity + Terraform
  FIC). Connecting on the old secret shape fails (`ParameterNotDefined: token`) or signs in against a
  redirect Entra doesn't know (`AADSTS50011`). Path that worked (rapid, 2026-11-12): cancel wizard →
  Custom connectors → Security → Azure AD → **Use managed identity** (tenant id, `api://<api>`,
  OBO `false`, scope with a **space** not a comma) → Update connector → put redirect+subject in
  tfvars → apply → Power Apps **Connections** (page search, not the global search box) → New
  connection → **OAuth Connection** → Create → pick the work account on the popup → status
  **Connected** → Copilot Studio Add tool → select that connection.
- Power Apps custom connectors / connections UI often lives in a **Power Automate iframe**; drive that
  frame, not only the outer `make.powerapps.com` shell.
- Preview proof (same day): `budgeting_get_forecast` and `budgeting_update_cost_centre_forecast`
  worked; credits left `0` once PAYG was linked (usage showed after the first tool call).
- The default **Conversational boosting** system topic (Standard) has a "Create generative answers"
  step that can show "Feature blocked by your environment" and block publishing. Deleting only that
  step breaks its Condition (`Topic.Answer`); remove the whole branch. Did not recur on the second
  Sandbox agent.
- **Publish needs at least one channel.** Only Microsoft 365 and Teams is allowed by the data policy.
  Untick "Make agent available in Microsoft 365 Copilot" (ticked by default) unless that's wanted.
- A new connection makes the first chat message ask to "verify your credentials". Open the connection
  manager (already Connected), then start a **new test session**.
- The Tools page can show "Connector request failed" `[{"jsonrpc":"2.0"}]` while chat works.
- Event and recurrence triggers: **add trigger**, test with the flask icon (replays a past firing),
  then **publish** (an unpublished agent doesn't react). Triggers use the maker's credentials.
  The Recurrence trigger needs the Copilot Studio connector allowed in the data policy.
- Trigger runs from the Power Platform virtual network reach the gateway from the delegated subnet (10.40.5.x).
- Agent runs of unpublished agents don't fire. Test pane runs aren't billed.
- A Recurrence trigger set to 30 minutes first fires at creation (publish the agent first, or that run is
  lost), then every 30 minutes. The Activity page lists runs as "Automated". Delete the trigger after
  testing; it can't be undone, and deletes from published versions too.

## Observability

- `ApiManagementGatewayLogs` first rows appear 40-50 minutes after API Management is created; the MCP log table
  earlier. Alert rules fired correctly once rows existed.
- Entra tables (`SigninLogs` and others) stayed **empty** for 6+ hours despite an enabled diagnostic
  setting with all categories, P2 licensing and real sign-ins. Cause not found; check the setting's
  status in the Entra admin center.
- **An email receiver must be verified.** Alert emails never arrive until the receiver has clicked the
  verification link, yet `emailReceivers[].status` still reads `Enabled`, and the link expires quickly.
  Check with `az monitor action-group test-notifications create` (it fails with "no valid receivers" for an
  unverified address). To re-send the verification, recreate the action group
  (`terraform apply -replace='module.gateway.azurerm_monitor_action_group.alerts[0]'`).
- KQL: `last` is reserved; don't use it as a column name.

## Driving the browser

- Waits are capped at 10 seconds; a batch of more than about 12 waits times out. Use a background
  `until` loop for long waits, not chained sleeps.
- Clicks sent before a page finishes loading are lost; screenshot first, then click.
- Signing out can drop the browser tab group; recreate it with `tabs_context_mcp` (createIfEmpty).
- A "Leave site?" dialog blocks navigation when a draft has unsaved changes; open a new tab.
- Don't read credentials from the page or the clipboard. The admin APIs give what you need.

## Dead ends (don't retry)

- Reading billing plans with `az rest` or the Terraform data source as the personal account (403).
- Using the Azure account's `systemId` as the billing policy ID.
- Linking a Developer environment to a billing plan, or converting it. Create Sandbox from the start
  (rapid included); don't try to "upgrade" Developer later.
- Reusing an old `copilot_connectors` redirect/subject after the environment (or connector) was
  recreated. The new redirect looks like `…/redirect/new-5fcontoso-20finance-20tools-5f…`; the old
  `cr547-5f…` entry must be replaced, not left alongside a dead key.
- Creating the Power Apps connection before managed identity + FIC apply (`AADSTS50011` /
  `ParameterNotDefined`).
- Enabling the knowledge feature to clear the generative-answers error: it weakens the allow-list.
- Searching for the connector in the publish error: the `BlockedConnector` message doesn't name it.
  (This was seen on the Developer environment; it didn't recur on the Sandbox.)

## External guidance to check your work against

Distilled from a Microsoft Learn review on 2026-11-12 (the original notes are not kept). Everything
here is Microsoft's documentation, **not verified by testing here** unless it says so. The links came
from that review and were not re-opened; check one before relying on it.

**Copilot Studio and MCP**

- MCP tools need **generative orchestration**, and the transport must be **Streamable HTTP**: SSE is
  unsupported in Copilot Studio ([Connect an existing MCP server](https://learn.microsoft.com/microsoft-copilot-studio/mcp-add-existing-server-to-agent)).
- **Tool schema quirks that filter or corrupt tools:** multi-type arrays are truncated, reference-type
  inputs filter the tool out, enums are read as strings, and an integer `exclusiveMinimum` throws
  ([MCP troubleshooting](https://learn.microsoft.com/microsoft-copilot-studio/mcp-troubleshooting)).
  Keep tool parameters to plain scalars and string enums.
- A Microsoft Copilot harness agent caps how many MCP servers run at once in a conversation. Keep the
  number of servers per agent small.
- **Confirmation for writes.** Microsoft 365 Copilot and Cowork honour the MCP `readOnlyHint` and
  `destructiveHint` annotations. Copilot Studio's documentation doesn't promise an equivalent. Don't
  assume annotations produce a confirmation dialog until probe 9 in
  [docs/ai-safety.md](docs/ai-safety.md#probes) is run on each harness.

**Entra ID and connectors**

- A federated identity credential's issuer, subject and audience must match **case-sensitively**. A
  wrong subject saves without error and fails at token exchange (`AADSTS70021`). The audience is almost
  always `api://AzureADTokenExchange`
  ([considerations](https://learn.microsoft.com/entra/workload-id/workload-identity-federation-considerations)).
- Exporting and importing a custom connector creates a **new managed identity subject**, which must be
  registered again.
- **The on-behalf-of hop takes delegated scopes, never app roles**, and isn't for app-only callers.
  Azure SQL's only delegated scope is the coarse `user_impersonation`, so least privilege has to be
  enforced in the database (contained users and roles, as `sql-setup.py` does).
- A Copilot Studio **Agent ID** is a Microsoft-managed identity for governance and Conditional Access.
  Tenants can't mint tokens as it, so it doesn't replace the connector's client app.

**Billing and environments**

- **Unmanaged Developer environments are being deprecated** (Microsoft gives 2026-12-15). Pay-as-you-go
  already supports only Production and Sandbox. The module still defaults `environment_type` to
  Developer: check the date and change the default if it holds.
- The Microsoft Copilot harness is billed in Copilot Credits **from build and preview**; the standard
  harness often only after publishing.
- Azure budgets and alerts **don't stop** pay-as-you-go usage. Use the agent's **Stop usage** limit, and
  untick the separate **Windows 365 for Agents** meter in the billing plan wizard.

**API Management**

- Enabling MCP **payload logging** (arguments and results) is opt-in and risky; scrub before enabling,
  and never in a shared workspace ([Monitor MCP servers](https://learn.microsoft.com/azure/api-management/monitor-mcp-servers)).
- Global **Frontend Response body logging** breaks MCP streaming, as does reading
  `context.Response.Body` in an MCP policy.
- `llm-content-safety` can inspect MCP tool arguments and results. Not tried; try it only after the
  indirect-injection probe, because it adds latency, a dependency and false positives.
- Advanced connector policies are not yet a replacement for classic data policies for custom
  connectors. Keep the classic policy in [governance.tf](infra/modules/contoso-gateway/governance.tf).

**Parked, on purpose:** the standalone AI Gateway product (preview, East US 2 and Sweden Central only),
Foundry's bring-your-own gateway, Agent 365 tool governance, API Center as an MCP catalogue, and
continuous access evaluation on the gateway. See [docs/going-further.md](docs/going-further.md#microsofts-ai-gateway-offerings-measured-against-this-design).

## Teardown

Follow [docs/deploy.md](docs/deploy.md#teardown) exactly; it is the tested order for both profiles. Notes for
an agent on top of it:

- **Never chain plan and apply.** Plan to a file, show it, apply the file.
- **Never destroy `azuread_service_principal.msgraph` or `.azuresql`.** They are the tenant's own
  (`use_existing = true`). Remove them from state first. Destroying Graph's deletes it for the whole
  tenant, with every app's consent grants.
- The first destroy fails at the resource group (Azure's auto-created smart detector rule and action
  group; in secure, the `NWTA-` data collection rule and endpoint). Delete them, re-plan, apply.
- The data policy can survive a destroy. If the admin center still lists it, delete it there or with
  `DELETE .../scopes/admin/apiPolicies/<id>?api-version=2016-11-01`.
- With a billing plan, delete the environment in the admin center, not through Terraform (the provider
  calls a billing API that returns 403 for a guest principal), then `state rm` it.
- Soft-deleted API Management instances purge slowly (minutes each):
  `az apim deletedservice purge --service-name <name> --location <region>`.
- A published agent with a Recurrence trigger bills each firing. Delete the trigger after testing.
- Roles granted for the build (subscription Contributor, Power Platform Administrator) are revoked
  last, and only when the user asks.

## Learned from the first Microsoft Copilot harness run (rapid profile)

- **Billing plan outlives the environment.** `contosodevpayg` survived the teardown and Terraform recreated
  the same resource group name. The new Sandbox was created by Terraform with no `billing_policy_id`
  (so a guest principal works), then linked in the admin center (Licensing → Billing plans → Edit → Add or
  remove environments). Delete the plan before destroying its resource group.
- **A new Sandbox gives the maker no role.** Copilot Studio silently opens the Default environment until
  the maker is added: admin center → the environment → Membership → Add me. The new Copilot Studio has
  no environment picker; use More → Open classic experience, which asks you to accept a terms dialog.
- **Connectors:** add one MCP server per domain from the agent's Tools → Add → MCP, all on the agent's own
  client app. The redirect URL is readable from the dialog's input; the exact managed-identity subject
  comes from the admin API (`az rest ... /apis?$filter=IsCustomApi eq true`, then
  `connectionParameters.token.oAuthSettings.properties.FederatedIdentityCredentials`).
- **A new connection needs a human**: a sign-in popup on the desktop. Don't delete a pending connection.
- **Copilot Studio Evaluate** failed to load ("Can't load data") on a draft agent. Not resolved.
- The Microsoft Copilot harness agent editor has **no Triggers section** here (Microsoft documents one, in preview); channels are Teams and Microsoft
  365, a demo website and an app. Its MCP tool dialog has per-tool permission toggles (enable or disable),
  not an approval prompt. It also keeps the "Search all websites" knowledge source by default; the data
  policy blocks it.
- `ApiManagementGatewayMCPLog.ClientName` is `McpToolsListClient` / `AgenticLoop` for this harness.
- The finance `cost_centres.name` column is 80 characters, which limits injection-style test data.
- Gateway logs on Basic v2 did not record query strings, contrary to an earlier observation.
