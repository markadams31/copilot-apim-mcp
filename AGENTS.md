# AGENTS.md

For AI coding agents setting up, running or changing this project. People should read
[README.md](README.md) and [docs/](docs/) instead; this file is terse on purpose and records what was
learnt the hard way. Everything below was observed in one tenant (2026-11-09 to 11-23) unless it says
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

- Standard harness agents work in the **Test your agent pane without credits**. **Publishing** needs a licence:
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
- Unmanaged Developer environments stop working on 2026-12-15 (Learn). Prefer Sandbox regardless. A free
  Developer environment is fine for a throwaway, Preview-only test of the standard harness with no gateway
  (as in [standard-harness-exploration.md](docs/standard-harness-exploration.md)); it can't publish.

## Terraform

- First apply: `-parallelism=1`. Concurrent MCP tool writes return 412 Precondition Failed.
- Updating an `azapi_resource` MCP server, even only its description, **deletes its tools** while state
  still lists them. The server has `ignore_changes = [body]`. To change one, taint it.
- `terraform plan` always shows a few cosmetic changes (the MCP and API policies, Entra
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

- **Neither harness is the default.** Standard (Home → Other ways to build → Agent) and Microsoft Copilot (Home →
  **Agent**; formerly the GitHub Copilot harness, and the portal may still say either) both exist and suit
  different work; choose with the table in [docs/deploy.md](docs/deploy.md#which-harness-and-copilot-credits).
  Gateway / connector / Terraform steps are the same; editor and billing differ. The Copilot harness needs
  Sandbox + pay-as-you-go or Preview says `EnforcementUsageCredits`; the standard harness tests without credits.
- **When testing knowledge answers in Preview**, files added as knowledge show Ready but weren't searchable for about
  an hour (2026-11-23), and a topic-narrowing instruction can make the agent refuse in-scope questions. Don't read a
  "couldn't find it" from a fresh upload as a retrieval limit; see [standard-harness-exploration.md](docs/standard-harness-exploration.md).
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
  Custom connectors → Security → Microsoft Entra ID → **Use managed identity** (tenant id, `api://<api>`,
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
- With no browser tools, start a separate Chrome with `--user-data-dir=<scratch dir> --remote-debugging-port=9222
  --remote-debugging-address=127.0.0.1` and drive it with Playwright's `connect_over_cdp`. A person signs in once
  (MFA) in that window. The profile holds work-account cookies, so keep it out of the repo, and stop Chrome by PID,
  not `pkill -f`. Force a large viewport, and read a screenshot to confirm state before acting.

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
- Raising `runtime_version` on a Flex Consumption Function app and deploying with the remote build
  (`--build-remote true`). The app showed Python 3.13, but the build host still ran 3.12.2, so
  `azure-functions` 2.x (needs 3.13 or newer) couldn't be installed, three times, even after a restart.
  `scripts/deploy-function.sh` now builds the packages locally for Linux and Python 3.13 and ships them
  in the zip; keep its `python_version` equal to `runtime_version` in `backend.tf`.

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
  assume annotations produce a confirmation dialog: probe 9 in [docs/ai-safety.md](docs/ai-safety.md#probes)
  found a per-server "Ask the end user before running" setting on the standard harness and none on the
  Microsoft Copilot harness.

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
- A Copilot Studio **agent identity** (Microsoft Entra Agent ID; Copilot Studio labels it "Entra Agent ID") is a Microsoft-managed identity for governance, created when the agent is
  created (standard harness) or first published (Microsoft Copilot harness). Tenants can't mint tokens as
  it, and an agent identity can't start an interactive sign-in, so it doesn't replace the connector's
  client app. Custom connectors and MCP servers add no API permissions to it, and Conditional Access on it
  is enforced only in Teams today. See [concepts.md](docs/concepts.md#agent-identity-and-client-app-registration-two-different-things).
- **Agent identities outlive a destroyed environment.** Eight were left behind by earlier teardowns. Check for
  them after a destroy (deploy.md teardown step 10) and delete any whose agent is gone.

**Billing and environments**

- **Unmanaged Developer environments are being deprecated** (Microsoft gives 2026-12-15). Pay-as-you-go
  already supports only Production and Sandbox. The module and both profiles default `environment_type`
  to Sandbox, so new builds aren't affected.
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
Microsoft Foundry's bring-your-own gateway, Microsoft Agent 365 tool governance, API Center as an MCP catalogue, and
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
- **Always purge the soft-deleted API Management instance** (deploy.md teardown step 9; about 6 minutes each,
  `az apim deletedservice purge --service-name <name> --location <region>`). On 2026-11-18 a rebuild while the
  previous instances were still soft-deleted got 502 on every MCP tool create, and Terraform retried for the
  full 5-minute timeout per tool. A direct PUT of the same body under another name succeeded in under a second.
  Purging afterwards didn't clear it at once, so a delay is possible. **Workaround, not in the code:** append
  `-${random_string.suffix.result}` to the `name` of `azapi_resource.mcp_tool` in `gateway.tf` (that made every
  tool create succeed in about a second); remove it again once the soft-deleted instances are gone.
- A published agent with a Recurrence trigger bills each firing. Delete the trigger after testing.
- Roles granted for the build (subscription Contributor, Power Platform Administrator) are revoked
  last, and only when the user asks.

## Learned from the first Microsoft Copilot harness run (rapid profile)

- **Billing plan outlives the environment.** `contosodevpayg` survived the teardown and Terraform recreated
  the same resource group name. The new Sandbox was created by Terraform with no `billing_policy_id`
  (so a guest principal works), then linked in the admin center (Licensing → Billing plans → Edit → Add or
  remove environments). Delete the plan before destroying its resource group (deploy.md teardown step 5); Terraform never removes it, and the next build needs a new plan.
- **A new Sandbox gives the maker no role.** Copilot Studio silently opens the Default environment until
  the maker is added: admin center → the environment → Membership → Add me. The new Copilot Studio has
  no environment picker; use More → Open classic experience, which asks you to accept a terms dialog.
- **Connectors:** add one MCP server per domain from the agent's Tools → Add → MCP, all on the agent's own
  client app. The redirect URL is readable from the dialog's input; the exact managed-identity subject
  comes from the admin API (`az rest ... /apis?$filter=IsCustomApi eq true`, then
  `connectionParameters.token.oAuthSettings.properties.FederatedIdentityCredentials`).
- **A new connection needs a human**: a sign-in popup on the desktop. Don't delete a pending connection.
- **The "Add MCP server" wizard "hangs" when the create call returns 409.** The Add button greys out and the dialog
  never closes, with no error. The browser's network log shows `POST …/api/botmanagement/v1/environments/<env>/connectors/apim`
  answering **HTTP 409 (Conflict)** after about two minutes, and no connector exists. It failed five times with the
  server name "Contoso Directory (Employee)" (including with a different URL), and **succeeded on the first try
  with a different name, "Contoso Employee Directory"**, with every other value identical (it appeared in the API
  list about two minutes later). So the conflict is on the **name**: most likely an earlier failed attempt left a record
  that the connector list doesn't show, though the parentheses could also matter (not separated). If the wizard
  spins, check the network log for a 409 and **change the server name**. The wizard fields (Manual, client id,
  placeholder secret, Entra URLs, scope) are in docs/add-mcp-tool-to-agent.md.
- **Finding the connector's managed-identity subject (changed).** On 2026-11-16 the Power Platform admin API listing
  (`…/scopes/admin/environments/<env>/apis?$filter=IsCustomApi eq true`) no longer returned
  `FederatedIdentityCredentials` for any connector, including ones that work, and the CLI guest could not read the
  connector through Dataverse. The subject has the form
  `/eid1/c/pub/t/<tenant>/a/<app>/<region>_<connector name>`; the `t/…/a/…` part is the same for every connector in a
  tenant, so copy an existing connector's subject and change only the last segment to the new connector's name
  (for example `australia-001_new-5fcontoso-20employee-20directory-5f61f3160b34451360`). It worked first time: the
  connection signed in, and Entra would reject a wrong subject. The Power Apps *Custom connectors → Security* box
  also shows the subject if you can read it. The editor's Client ID field goes blank once managed identity is selected.
- **The connection sign-in popup is blocked when my automation clicks Create.** The panel then says "Unable to sign
  in. Please try again." A person clicking **Create** gets the popup (allow popups for copilotstudio.microsoft.com).
- **Copilot Studio Evaluate** failed to load ("Can't load data") on a draft agent. Not resolved.
- The Microsoft Copilot harness agent editor has **no Triggers section** here (Microsoft documents one, in preview); channels are Teams and Microsoft
  365, a demo website and an app. Its MCP tool dialog has per-tool permission toggles (enable or disable),
  not an approval prompt. It also keeps the "Search all websites" knowledge source by default; the data
  policy blocks it.
- `ApiManagementGatewayMCPLog.ClientName` is `McpToolsListClient` / `AgenticLoop` for this harness.
- The finance `cost_centres.name` column is 80 characters, which limits injection-style test data.
- Gateway logs on Basic v2 did not record query strings, contrary to an earlier observation.

## Teams and workflows: what we learned (2026-11-16)

- **Publishing an agent to Teams (Microsoft Copilot harness):** the Build tab's Channels "+" offers
  *Teams + Microsoft 365* and *App*; *Demo website* is greyed out by the data policy. Pick **Microsoft
  Teams only** or *Microsoft Copilot and Microsoft Teams*: the setting can't be changed after publishing.
  Add the channel, **Publish** again, then *Use and share → View in Microsoft Teams* opens the install card.
  Memory is a toggle on the same panel (off by default).
- **Who can do what.** The licensed work account here holds only *Power Platform Administrator*, so the
  Teams admin center refuses it ("You don't have access"). The Global Administrator was a separate guest
  login with **no Teams license**, so Graph Teams endpoints (`/appCatalogs/teamsApps`) fail for it with
  "Failed to get license information for the user". To open the Teams admin center as the licensed
  user, assign *Teams Administrator* (template id `69091246-20e8-4a56-aa4d-066075b2a7a8`) with
  `POST /roleManagement/directory/roleAssignments`, then **sign out and back in**: an existing browser
  session won't carry the new role.
- **Teams install worked in the end, and we did not change anything that fixed it.** The first two **Add** attempts in
  Teams on the web (about two hours after the channel was added and the agent republished) ended with "App
  package can't be uploaded. Unknown Exception". A **third attempt succeeded**; the agent's greeting is
  timestamped 04:23 UTC in the chat. We had granted **no** role yet (Teams Administrator 04:26 UTC, AI
  Administrator 04:41 UTC, from the tenant audit log), changed **no** policy, and the Teams and Microsoft 365
  admin centers were still failing an hour later. So the cause was a delay in a brand-new tenant, not a missing
  permission. We cannot prove which delay (Teams app provisioning, the agent's catalog entry, or the trial
  tenant's backend). The click that worked was not watched, so we don't know whether it simply retried the
  same call.
- **What to do if you hit it:** add the Teams channel (Teams only unless you need Copilot), republish, use *Use
  and share → View in Microsoft Teams*, and press **Add**. If you get "App package can't be uploaded", **wait
  and retry; give a new tenant a few hours before changing any policy or role**. You do not need the Teams
  or Microsoft 365 admin centers for an end user to install a shared agent. The sign that it worked is the
  button changing from Add to **Open** and the agent appearing in the Chat list. In the chat the user sees
  streamed steps ("Calling directory_get_my_profile…"), then the answer; no connection prompt appeared for the
  maker, whose connections already existed.
- **"App package can't be uploaded. Unknown Exception"** on Teams *Add* (resolved by waiting, see above): the agent never reached the app
  catalog. At the time, the Teams admin center said app management was being set up (up to 30 minutes)
  and its Actions menu (Upload new app, Org-wide app settings) was greyed out. Retry after the banner
  clears before changing anything. **App permission policies are retired** in this tenant (the page redirects to
  Manage apps); app availability and custom-app interaction are now managed under *Manage apps → Org-wide app
  settings* and per-app availability, so look there, not in Permission policies.
- **Things we tried that turned out not to be needed** (so you can skip them): granting the work account *Teams
  Administrator* and then *AI Administrator*; signing in to the Teams and Microsoft 365 admin centers; checking
  app permission policies (retired in this tenant); loosening the data policy. The *Agent and plugin access* and
  *User access* panels in the Microsoft 365 admin center kept showing "Error fetching settings" even with AI
  Administrator, and Teams *Org-wide app settings* stayed greyed out, yet the install worked. **A Global
  Administrator that is a guest backed by a personal Microsoft account cannot sign in to these admin portals**
  ("Login is not supported for consumer users"); create a cloud-only admin user if you need them.
  Role changes take effect in the browser only after you sign in again.
- **Where Microsoft says to look when an agent can't be installed** (Learn: "Your organization has prevented
  this agent from being installed"): Microsoft 365 admin center → *Agents → Settings → Agent and plugin
  access* ("Allow agents and plugins built by your organization") and *User access*; Teams admin center →
  *Manage apps → Org-wide app settings* (custom apps). An agent shared by a Copilot Studio install link is
  governed by *Let users interact with custom apps in preview*; once it is in the org catalog, per-app
  availability and Status govern it instead. Settings take a few hours; app availability up to 24 hours.
  Community fixes: toggle the Teams channel off and on and republish; use the install link from the
  publish dialog. No source matched the exact "App package can't be uploaded" text.
- **Workflow with an Agent node: it worked once the data policy had propagated.** Publish succeeded about 2h40
  after the last policy change; the first run fired on publish and took 16 s (about 0.26 credits). The agent
  returned the maker's directory profile and the cost centres; the gateway log showed both tool calls. The
  workflow's **Enabled toggle** on *Workflows* (left menu) stops the schedule; its row's *More actions* menu was
  disabled right after switching it off, so delete it later (or from the Power Automate portal). Always turn it off
  after a test: it bills every run.
- **A workflow's Agent node needs the Agents connector (`shared_agentnode`)** in the data policy
  (`allow_workflow_agents`). Connection creation can succeed while **Publish still fails**: the designer's
  generic "couldn't load suggestions for some fields" banner hides Dataverse error `0x80060467` wrapping a
  **442** DLP block on `GetOutputSchema`. To read it, wrap `window.fetch` in the page before clicking
  Publish and search the failed `$batch` response for `Last refresh`; that time is the policy cache's,
  and it can lag the policy by hours. Compare it with the policy's `lastModifiedTime`:
  `az rest` against `https://api.bap.microsoft.com/providers/PowerPlatform.Governance/v2/policies?api-version=2016-11-01`
  (resource `https://api.bap.microsoft.com/`). No API shows enforcement directly; replaying the connector
  call from the CLI fails ("missing connection ACL"), because the connection belongs to the browser session.
- **`permissive_data_policy`** (default false) classifies unlisted connectors as Business
  instead of Blocked. The provider's group names differ: the policy default uses `Confidential` for Business,
  the custom-connector patterns use `Business`. Use it only in short-lived test environments.
- **Chat context in Teams** persists across days; there is no "new chat" button, and typing *Restart* or *Start
  again* doesn't clear it (below). The Microsoft Copilot harness keeps the last 100 messages. Design repeatable tasks around one
  conversation per task. See the research in [testing.md](docs/testing.md#evidence-gaps).
- **Don't click the red badge on a workflow node**: it is the delete button, not an error indicator.

## Calling a Microsoft Copilot harness agent from your own web page (2026-11-16)

Worked end to end when Teams and the admin portals were failing. A browser page signs the user in with Entra
and chats with the published agent; the agent called both tools through the gateway.

- **Start from Microsoft's sample, don't write one:** `microsoft/Agents` → `samples/nodejs/copilotstudio-webclient`
  (about 4 KB: `index.html`, `index.js`, `acquireToken.js`, `settings.TEMPLATE.js`, MIT). It loads Web Chat,
  msal-browser and `@microsoft/agents-copilotstudio-client` from unpkg at pinned versions. Serve the `web`
  folder on `127.0.0.1:5500` (`python3 -m http.server 5500 --bind 127.0.0.1`).
- **Use `directConnectUrl`, not `environmentId` + `schemaName`, for this harness.** With the environment id and
  schema name the sample reaches the classic runtime and the agent answers "This action doesn't support
  agents built with the GitHub Copilot harness" (the message still uses the old name). Copy the **connection string** from the agent's *Channels →
  + → App → Microsoft 365 Agents SDK* panel into `directConnectUrl`; it points at
  `…/copilotstudio/agenticruntime/3p/dataverse-backed/authenticated/bots/<schema name>/conversations?api-version=2022-03-01-preview`.
  The channel is not added unless you save it; closing the panel changes nothing.
- **App registration** (Microsoft's README): single-tenant, platform *Single-page application*, redirect
  `http://localhost:5500` (the port must match), no secret, delegated permission
  *Power Platform API → CopilotStudio → `CopilotStudio.Copilots.Invoke`* (scope id
  `204440d3-c1d0-4826-b570-99eb6f5e2aeb` on app id `8578e004-a5c6-46e7-913e-12f58912df43`, which already
  existed in the tenant). The first sign-in shows a consent screen ("Allows Invoking Copilots", "Sign you in
  and read your profile"); the user accepts it. The sample requests `https://api.powerplatform.com/.default`.
- **The sample's `loginPopup` is blocked by Chrome** (`popup_window_error`) because it is not user-initiated.
  Swap it for `handleRedirectPromise()` + `loginRedirect()` in `acquireToken.js` (same-tab redirect). Hard
  reload (`Ctrl+Shift+R`) after editing, or the browser serves the cached script.
- **Result:** the agent greeted the user, returned the directory profile and the cost centres, and said the
  cost-centre service ran under its own identity and recorded the user as the asker, as designed.
- **Create the registration with the CLI** (single-tenant SPA, no secret; the `notes` field says what it is):
  ```bash
  az rest --method post --url "https://graph.microsoft.com/v1.0/applications" \
    --headers "Content-Type=application/json" --body '{
      "displayName": "Copilot Studio web client (test, delete when done)",
      "signInAudience": "AzureADMyOrg",
      "spa": { "redirectUris": ["http://localhost:5500"] },
      "requiredResourceAccess": [{ "resourceAppId": "8578e004-a5c6-46e7-913e-12f58912df43",
        "resourceAccess": [{ "id": "204440d3-c1d0-4826-b570-99eb6f5e2aeb", "type": "Scope" }] }]}'
  ```
  Put the returned `appId` and your tenant id in the sample's `settings.js` (`appClientId`, `tenantId`).
- **The one code change**, in `acquireToken.js`: after `await msalInstance.initialize()` add
  `const r = await msalInstance.handleRedirectPromise(); if (r) return r.accessToken`, and replace the final
  `loginPopup(...)` call with `await msalInstance.loginRedirect(loginRequest); return new Promise(() => {})`.
- **Governance note:** this is a public client with a delegated permission only (no secret, nothing app-only).
  It is a test tool; it is deliberately not part of the repo's deliverable, so keep it out of the reference solution.
- **Throwaway:** the registration was "THROWAWAY Copilot Studio SPA test (delete me)" created with
  `POST /applications`; delete it with `az ad app delete --id <appId>` and stop the local server when done.

## What a long chat costs, Restart, and Monitor (2026-11-16)

- **"Restart" and "Start over" don't reset a Teams chat with a Microsoft Copilot harness agent.** They are ordinary
  messages: the agent replies "I can't clear this chat myself" and still recalls earlier content. The agent's Teams
  menu has only *About* and *Share app*, so a user cannot start a new conversation; Preview's **New chat** can.
  Design repeatable tasks so one task never depends on a clean thread (see docs/ai-safety.md, docs/deploy.md).
- **Conversation cost (Preview's credit counter, estimates).** One question that made about 13 spend calls
  (`finance_query_spend` has no cost-centre filter, so the agent splits a 12-month question by month) cost 29.55
  credits. Three follow-ups that needed no new tool calls then added 4.74 together, about 1.6 each, against a
  fraction of a credit for a fresh short chat. The counter updates minutes after a turn; read it with
  `button[aria-label*="estimated usage"]` and its parent's text rather than a screenshot.
- **Monitor works; Preview's History is empty.** *Monitor* lists published-channel sessions with channel names
  (Teams shows as "Microsoft Teams", the custom web page as "M365 agents SDK client"), credits and tool use.
  Preview chats don't appear in Monitor or History. Evaluate still failed on a fresh load.
- **A "soft" confirmation works if you add it to the instructions** (docs/ai-safety.md): append "tell the user the
  cost centre, year, current and new amounts, and write only after a clear yes in a later message". Edit it in the
  draft and test in Preview without publishing; restore the original text and Save afterwards.
- **Employee Assistant in Teams installed first time** (about three hours after the Finance Assistant's third
  attempt). It needs republishing after you add its tool, and the editor warns "unsaved changes" until you do.
- **Wizard and connector gotchas** for a second agent are in the section above (409 on a reused name, derived
  subject, popup blocked when an automated click presses Create).

## Approvals, second user and auditing (2026-11-17)

- **Workflow connector catalogue.** The workflow designer's Connector action lists public connectors only; the
  custom MCP connectors are not offered, so a workflow can't call an MCP tool. Connector actions in a workflow
  started by "When an agent calls the flow" run as the **invoking user** (Learn), so a gateway can't tell that
  workflow from any other flow. A write gate built on a workflow was discussed, not built.
- **Workflow editor** drops characters typed fast into dynamic fields: type short chunks, and insert tokens with `/`
  then Down and Enter. Ctrl+S saves. A published agent flow or workflow isn't needed to test the draft.
- **Standard harness agent**, to test "Ask the end user before running": Home → Other ways to build → Agent
  (Standard). The setting is under the MCP server tool's Additional details and **needs a message**; without one the
  call fails closed with `InvalidContent`. Save the tool page, then test in the Test your agent pane. On the
  Outlook connector (2026-11-20) the approval did run the call on "Yes"; on the MCP connector it did not.
- **Second user.** `scripts/smoke.py` and `call-tool.py` take `CONTOSO_MSAL_CACHE` (a separate token cache file) and
  `CONTOSO_LOGIN_AS` (a login hint) so a second account doesn't overwrite the first's sign-in. A new member account
  needs Entra group membership (Terraform) and its own Dataverse user (it is in the environment users group).
- **Dataverse auditing** can be switched on for the environment, but the agent tables can't be audited. The Azure CLI
  guest identity is an unlicensed Dataverse administrator: it can read the organisation and audit settings but not
  `bot` or `botcomponent`, and `PublishAllXml` returns 403. Use the portal as the work account.
- **Three backends, one Function app each** (directory, finance, budgeting): `scripts/deploy-function.sh` deploys all
  three; the directory app has no database. Replacing an APIM API (here `internal-systems` was split into `directory`
  and `finance`) fails with "API cannot be deleted since it is referenced by at least one MCP tool", because the
  tools' old `operationId` still points at it. Apply the tool updates first
  (`terraform apply -target=module.gateway.azapi_resource.mcp_tool`, `-parallelism=1`), then a plain apply.
- **A new profile output is only visible after an apply** (`directory_function_name` was missing until then). Add new
  variables and outputs to both profiles; `scripts/check-profiles.sh` fails if their `variables.tf` or `outputs.tf` differ.
