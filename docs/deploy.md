# Deploy

Everything needed to stand up a deployment, from accounts to agents, and to remove it again. The
sequence is in [Stand up the stack](#stand-up-the-stack); what must exist first is in
[Prerequisites](#prerequisites); everything it creates is itemised in
[What gets created](#what-gets-created); removal is in [Teardown](#teardown). Maker steps in the Copilot Studio
and Power Apps portals are in [add-mcp-tool-to-agent.md](add-mcp-tool-to-agent.md).

## Prerequisites

Everything you need before Copilot Studio agents can call internal APIs through API Management over a
private network. Each table says what Terraform creates; everything else has to exist first, or be
done by someone. The network requirements apply to the secure profile only.

For what each term means, see [concepts.md](concepts.md).

### 1. Accounts and roles

| Requirement | Why | Notes |
|---|---|---|
| **A Microsoft Entra tenant** | Everything authenticates against it | Its country determines where identity data is stored |
| **A work (member) account for every agent maker** | **Copilot Studio rejects personal Microsoft accounts** (outlook.com, hotmail.com) | If the tenant was created from a personal account, its owner signs in as a *guest* (`#EXT#`) and can't build agents. Create a member account for them |
| **An administrator to run Terraform**, with: Azure **Owner** (or Contributor plus User Access Administrator) on the subscription; Entra rights to create app registrations and grant **admin consent** (Global Administrator, or Application Administrator plus Privileged Role Administrator); **Power Platform Administrator** | Terraform creates Azure resources, app registrations, role assignments, the Power Platform environment and the enterprise policy link | Signed in with `az login` |
| **MFA for every account** | Sign-in to Copilot Studio and the agents | Security defaults or Conditional Access |

### 2. Licences

| Licence | Needed by | Why | Notes |
|---|---|---|---|
| **Copilot Studio**: a Copilot Studio licence, pay-as-you-go billing, or the trial | Makers | Building agents and **adding tools**. Without it the Tools page says "Upgrade your license to start using tools" | The trial can build and test but not publish. Starting it asks for job title, company and phone |
| **Microsoft 365 E5**, or the E5 Compliance / Information Protection add-ons | **Every user of the environment** (makers and people chatting with the agents) | **Power Platform Virtual Network support** requires an E5-class licence | The E5 trial is 25 licences for a month and needs a payment method plus a completed organisation profile |
| **Power Apps Developer Plan** | The maker who owns a Developer environment | Developer environments are tied to it | Free. Sandbox or Production environments need Dataverse capacity instead |
| Microsoft Entra ID P1 or P2 | Security and audit | Conditional Access, Microsoft Graph activity logs | Included in E5 |

#### Which harness, and Copilot Credits

Every Copilot Studio agent runs on a *harness*, chosen when the agent is created; an agent can't be
moved from one to the other ([Harnesses in Copilot Studio](https://learn.microsoft.com/microsoft-copilot-studio/harnesses-overview)).

| | Standard harness | Microsoft Copilot harness |
|---|---|---|
| Create it from | Home → Other ways to build → Agent (Standard) | Home → **Agent** (Agents list may say **Microsoft Copilot**) |
| Editor | Tabs: Overview, Knowledge, Tools, Topics | One page: Instructions, Model, Channels, Skills, Tools, Knowledge |
| Deterministic automation | Topics and agent flows | Workflows; no topics |
| Billing | Copilot Studio licence or capacity | **Usage-based: needs Copilot Credits in the environment**, including while building and testing |
| Tested here | Yes: Copilot Studio results in [testing.md](testing.md) | Yes: a lab agent on this harness, with the Finance Assistant's tools, on the rapid profile in a Sandbox with pay-as-you-go; forecast read and update through MCP |

The Microsoft Copilot harness was formerly called the GitHub Copilot harness, and the portal's Agents list
may still say either. The Power Platform admin center's **Harness** column (Manage → Copilot Studio) still
shows the old value, **GitHub Copilot**, as of 2026-11-17. It is a Copilot Studio framework, not the GitHub Copilot service. **This
repository prefers it** once a Sandbox with pay-as-you-go is in place.

The gateway, the connector and the tools are the same for both.
[add-mcp-tool-to-agent.md](add-mcp-tool-to-agent.md) covers both; its screenshots show the standard harness.

**An environment with no credits can't run a Microsoft Copilot harness agent.** The Preview tab answers "You
need credits to continue … This environment is out of credits" (`EnforcementUsageCredits`). A trial
environment has none. Event and scheduled triggers consume credits. A scheduled trigger was tested on the
standard harness, and a workflow with a Recurrence trigger on the Microsoft Copilot harness, each once
and as the maker ([going-further.md](going-further.md#agents-that-run-without-a-user)).

Ways to get credits (an administrator allocates them to the environment):

| Option | Commitment | Notes |
|---|---|---|
| **Pay-as-you-go** (a billing plan linked to an Azure subscription) | None up front; billed monthly | Budgets and alerts don't stop usage; set a limit on the agent with **Stop usage** to cap it |
| Prepaid capacity packs | Up-front purchase | Allocated in Licensing → Copilot Studio → Manage Copilot Credits |
| Copilot Credits pre-purchase plan | One-year commitment | Bought in the Azure portal; also needs a billing plan |
| A Microsoft 365 Copilot licence | Per user | Microsoft says it also enables the Microsoft Copilot harness |

**Pay-as-you-go supports only Production and Sandbox environments**
([FAQ](https://learn.microsoft.com/power-platform/admin/pay-as-you-go-issues-faq)). Terraform defaults
`environment_type` to **Sandbox**. Do not use Developer: it can't take a billing plan or be converted,
and the Microsoft Copilot harness Preview then fails with `EnforcementUsageCredits`. **Publishing, and
running anything on that harness, needs Sandbox linked to a billing plan.**

Setting up pay-as-you-go ([Set up pay-as-you-go](https://learn.microsoft.com/power-platform/admin/pay-as-you-go-set-up)):

- **The Power Platform admin center rejects personal Microsoft accounts**, as Copilot Studio does. Use
  a work account.
- That account needs the **Power Platform Administrator** role (or Global Administrator), or the
  Licensing pages say the information isn't available.
- It also needs **Contributor or Owner on the subscription**. A role on a resource group alone leaves
  the subscription greyed out under "Partial access".
- In the wizard, ticking the **Copilot Studio** meter also ticks **Windows 365 for Agents**, a
  separate paid product. Untick it.
- The plan creates a hidden *Power Platform account* resource in the resource group you choose. Delete
  the billing plan before destroying that resource group.

**Creating the Sandbox environment.** Set `environment_type = "Sandbox"`. If the account that runs
Terraform can't read the billing plan (a guest account, for example), Terraform can't create the
linked environment. Create it in the admin center instead (Manage → Environments → New: Sandbox,
Australia, Dataverse on, pay-as-you-go on, the plan chosen by name), then import it:

```bash
terraform -chdir=$P import module.gateway.powerplatform_environment.agents <environment ID>
```

The environment resource ignores later changes to its billing and Dataverse settings for the same
reason, so confirm in the admin center that Bing search and "move data across regions" are off.
[AGENTS.md](../AGENTS.md) has the detail.

### 3. Power Platform

| Requirement | Created by | Notes |
|---|---|---|
| **An environment** of type **Sandbox** (or Production) (**not Trial**, not Developer), **with Dataverse** | Terraform | In the same geography as your Azure regions. Here: `australia`. Developer can't take pay-as-you-go |
| **Managed Environment** turned on | Terraform | Required for Virtual Network support |
| **Generative AI data movement across regions: off**; **Bing search: off** | Terraform | Keeps processing in-geography with a supported model (see [governance.md](governance.md#data-residency-australia)) |
| **Enterprise policy (`NetworkInjection`) linked** to the environment (secure profile) | Terraform | Up to 30 minutes of instability after linking. Unlinking needs PowerShell (`Disable-SubnetInjection`) |
| **Control maker credential options: End-user credentials only** | An administrator, in the Power Platform admin center | Environment → Settings → Product → Features → Copilot Studio agents. Not done here ([governance.md](governance.md#known-governance-gaps)) |
| **Data policy**: an allow-list for the environment | Terraform ([governance.tf](../infra/modules/contoso-gateway/governance.tf)) | Allows custom connectors on your API Management host plus the Teams channel; blocks the rest. Your tenant may already have a policy that blocks custom connectors |

### 4. Azure

| Requirement | Notes |
|---|---|
| A subscription | Costs: see the [architecture.md](architecture.md#cost-of-this-demonstration) |
| `Microsoft.PowerPlatform` resource provider registered | Terraform registers it |
| **An API Management tier that supports a private gateway** (secure profile), available in your region | Classic Premium or Developer (internal mode), Premium v2 (virtual network injection), or Standard v2 with a private endpoint. Premium v2 creation is sometimes paused in a region for capacity. The rapid profile uses Basic v2, public, which creates in about two minutes |
| **VM quota** for the chosen size, if you deploy the DNS forwarder VM (secure profile) | New subscriptions can have zero quota for some families: `az vm list-usage -l <region>` |

### 5. Network (secure profile)

The rapid profile needs none of this; instead, put your public IP address in
`sql_firewall_ip_addresses` so `sql-setup.py` can reach the database.

| Requirement | Notes |
|---|---|
| Non-overlapping address space for the virtual networks and VPN clients | Here 10.40.0.0/16, 10.41.0.0/16, VPN 10.255.201.0/24 |
| **Two delegated subnets, one in each region of the Power Platform geography**, the **same size** | Australia: australiaeast and australiasoutheast. Size: 6–10 IP addresses per non-production environment, 25–30 per production environment, plus 5 reserved. You can't resize after delegation without unlinking |
| Both delegated subnets can **reach** API Management (peering) and **resolve** its name | Link API Management's private DNS zone to both virtual networks |
| Network security group on the API Management subnet admits the delegated subnets on 443 | |
| Explicit egress (NAT gateway or firewall) | New virtual networks have no default outbound internet access; API Management and the backends need Entra ID and Graph |

### 6. Identity configuration

All created by Terraform:

- The API app registration with the `Tools.Read` scope and admin-consented delegated permissions
  (Graph `User.Read`, Azure SQL `user_impersonation`).
- One app registration per agent, pre-authorised for `Tools.Read`.
- The app role `CostCentres.Read` on the API app, assigned to the maker (`cost_centres_user_upns`), and a
  user-assigned managed identity for each backend (directory, finance, budgeting), trusted by the API app as its credential.
- The security group **Contoso Finance Readers**, holding the maker by default (`finance_reader_upns`).
  `sql-setup.py` gives the group a database user, so its members can query spending.

Two values only exist after the agent's MCP connector is created, so they **loop back to Terraform**
(in `infra/profiles/<profile>/terraform.tfvars`, which is git-ignored; copy [terraform.tfvars.example](../infra/profiles/secure/terraform.tfvars.example)):

| Value | Where it appears | Terraform variable |
|---|---|---|
| The connector's **redirect (callback) URL** | Copilot Studio, when you add the MCP server | `copilot_connectors` (`redirect_uri`) |
| The connector's **managed identity subject** | Power Apps → Custom connectors → *connector* → Security, after choosing **Use managed identity** | `copilot_connectors` (`subject`) |

The issuer is always your tenant's, so Terraform builds it. Also set `maker_upn` there: the existing
work account that builds the agents (section 1).

### 7. Tooling (for whoever deploys and tests)

- Terraform ≥ 1.9, Azure CLI, [uv](https://docs.astral.sh/uv/)
- For testing the secure profile from a laptop: NetworkManager with the OpenVPN plugin (see [testing.md](testing.md))

### Learn more: prerequisites

- [Get access to Copilot Studio](https://learn.microsoft.com/microsoft-copilot-studio/requirements-licensing-subscriptions)
- [Power Platform licensing FAQ: Azure Virtual Network](https://learn.microsoft.com/power-platform/admin/powerapps-flow-licensing-faq#azure-virtual-network-vnet)
- [Set up virtual network support for Power Platform](https://learn.microsoft.com/power-platform/admin/vnet-support-setup-configure)
- [Managed Environments overview](https://learn.microsoft.com/power-platform/admin/managed-environment-overview)
- [Power Platform Terraform provider](https://registry.terraform.io/providers/microsoft/power-platform/latest/docs)

## What gets created

Everything a deployment puts into the tenant and the subscription, by layer. Use it to see the whole
footprint before you start, to review what a deployment leaves in your tenant, and to check teardown
found everything. The names use the Terraform `prefix` (for example `contosodev`); `<suffix>` is a
random five-character string.

**Created by** says how an object comes to exist: **Terraform**, **by hand** (a person in a portal,
following [add-mcp-tool-to-agent.md](add-mcp-tool-to-agent.md)), or **automatic** (a platform creates it
as a side effect, and Terraform doesn't know about it). Teardown removes the Terraform objects and
**finds** the others ([Teardown](#teardown)).

### Azure

All in one resource group, `rg-<prefix>-agent-gateway`.

| Object | Purpose | Created by | Profile |
|---|---|---|---|
| **API Management** `apim-<prefix>-<suffix>` | The gateway: validates the token, enforces each agent's allow-list, serves the MCP servers | Terraform | Both. Basic v2, public (rapid); Developer, internal (secure) |
| Three **APIs** (`directory`, `finance`, `budgeting`), their **policies**, two **MCP servers** (`directory-mcp`, `finance-mcp`) and five **tool definitions** | The REST operations and the MCP tools over them | Terraform | Both |
| API Management **logger** and **diagnostic** | Send gateway traces to Application Insights | Terraform | Both |
| Three **Function apps** (`func-<prefix>-dir-<suffix>`, `func-<prefix>-<suffix>` for finance, `func-<prefix>-budg-<suffix>`) on three **Flex Consumption plans** (FC1) | The directory, finance and budgeting backends | Terraform; code deployed by `scripts/deploy-function.sh` | Both |
| **Storage account** `st<prefix><suffix>`, containers `deploy`, `deploy-budgeting` and `deploy-directory` | Hold the Function packages | Terraform | Both |
| Three **user-assigned managed identities** (`id-<prefix>-directory-…`, `id-<prefix>-func-…`, `id-<prefix>-budgeting-…`) | The backends' credential for the on-behalf-of exchange, and for SQL (finance and budgeting) | Terraform | Both |
| **SQL server** `sql-<prefix>-<suffix>`, databases `finance` and `budgeting` (Basic), firewall rules | The demo data. Seeded by `scripts/sql-setup.py` | Terraform; data by script | Both. Client firewall rules apply to rapid |
| **Log Analytics workspace** and **Application Insights** | Gateway, Function and Entra logs | Terraform | Both |
| API Management **diagnostic setting** | Gateway logs to Log Analytics | Terraform | Both |
| **Action group** `<prefix>-alerts` | Emails alerts (only when `alert_email` is set) | Terraform | Both |
| Two **alert rules** (`authz-denial-spike`, `backend-errors`) | Alert on 401/403 spikes and backend 5xx | Terraform | Both |
| **Virtual networks** (primary and secondary region), subnets, **peerings**, **NSGs** | Private network, plus the two delegated subnets Power Platform needs | Terraform | Secure |
| **NAT gateway** and public IP | Outbound access for API Management and the backends | Terraform | Secure |
| **Private DNS zones** (Private Link and API Management), links, A record, **private endpoint** | Name resolution and private access to the backends and gateway | Terraform | Secure |
| **VPN gateway**, public IP, certificates (generated locally) | Lets a laptop reach the private gateway for testing | Terraform | Secure |
| **DNS forwarder VM**, network interface | Resolves the private names for VPN clients | Terraform | Secure |
| **Flow-log storage account** and **virtual network flow log** | Network audit trail | Terraform | Secure |
| **Enterprise policy** (`Microsoft.PowerPlatform/enterprisePolicies`) | Carries the delegated subnets to Power Platform | Terraform | Secure |
| **Power Platform account** (hidden resource) | Represents the billing plan in the resource group | **Automatic**, when the billing plan is made | Both, if pay-as-you-go |
| Smart-detector alert rule ("Failure Anomalies") and action group ("Application Insights Smart Detection") | Application Insights defaults | **Automatic** | Both. They block deleting the resource group |
| `NWTA-…` data collection rule and endpoint | Traffic Analytics | **Automatic** | Secure |
| `NetworkWatcherRG` | Azure's network diagnostics group | **Automatic**; free and recreated | Secure |
| **Soft-deleted API Management** | Azure's retention after delete | **Automatic**; free, purges itself | Both |

### Microsoft Entra ID

| Object | Purpose | Created by |
|---|---|---|
| **API app registration** `<prefix>-gateway-api`, its service principal, identifier URI, scope `Tools.Read`, app role `CostCentres.Read` | The resource the agents' tokens are issued for | Terraform |
| **Admin-consented delegated grants** on the API app (Graph `User.Read`, Azure SQL `user_impersonation`) | Lets the backends act on the user's behalf | Terraform |
| Three **federated identity credentials** (`function-managed-identity` for finance, `budgeting-function-managed-identity`, `directory-function-managed-identity`) | The Functions' managed identities as the API app's credential, so there's no secret | Terraform |
| `obo-fallback` **client secret** | Only if `obo_credential` is set to `secret`, which isn't recommended | Terraform |
| One **app registration and service principal per agent** (`<prefix>-employee-assistant`, `<prefix>-finance-assistant`), pre-authorised for `Tools.Read` | The caller identity the gateway checks against each agent's allow-list | Terraform |
| One **federated identity credential per MCP connector** (`copilot-<connector>`) | Trusts the connector's managed identity, so the connector holds no secret | Terraform, from the redirect URL and subject you copy out of the portals |
| **Groups**: `<organisation> Finance Readers (<prefix>)`, `<organisation> Budget Editors (<prefix>)`, `<prefix>-agents-environment-users` | Who may read spending, edit forecasts and use the environment | Terraform |
| **App role assignment** of `CostCentres.Read` | Which users may call the cost-centre tool | Terraform |
| **Tenant diagnostic setting** `<prefix>-to-log-analytics` | Sends sign-in and Graph activity logs to Log Analytics (the `entra_diagnostics` switch) | Terraform |
| **Agent identity** for each Copilot Studio agent (Copilot Studio labels it "Entra Agent ID"), a child of Copilot Studio's agent identity blueprint | Microsoft's directory record of the agent | **Automatic**: when the agent is created (standard harness) or first published (Microsoft Copilot harness). **Survives deleting the environment** |
| The tenant's **Microsoft Graph** and **Azure SQL** service principals | Terraform adopts them to grant consent. They belong to the whole tenant | Not created, **never destroy** (teardown step 3) |

### Power Platform

| Object | Purpose | Created by |
|---|---|---|
| **Environment** `<prefix>-agents` (Sandbox, Dataverse on) | Where the agents, connectors and connections live | Terraform, or by hand when the billing plan can't be read ([Licences](#2-licences)) |
| **Managed Environment** settings | Required for virtual network support; turns off cross-region data movement and Bing search | Terraform |
| **Data policy** `<prefix> agents: allow-list` | Allows custom connectors on the gateway host and the Teams channel; blocks the rest | Terraform |
| **Enterprise policy link** | Injects the environment into the delegated subnets | Terraform (secure) |
| **Billing plan** (pay-as-you-go) | Gives the environment Copilot Credits | **By hand**, in the admin center. Terraform never sees it |
| Copilot Credits allocation | Lets the Microsoft Copilot harness run | **By hand** |

### Copilot Studio, Power Apps and Teams

None of this is in Terraform. It lives inside the environment and goes when the environment is deleted,
except the agent identities above and the Teams installs.

| Object | Purpose | Created by |
|---|---|---|
| **Agents** (Employee Assistant, Finance Assistant) | What users talk to | By hand |
| **MCP tool registration** on each agent | Points the agent at a gateway MCP server | By hand |
| **Custom connector** for each MCP server | Created when you add the MCP server; its managed identity is what Entra trusts | By hand (steps 4 and 5) |
| **Connection** for each connector | The signed-in user's OAuth connection | By hand (step 7); each user makes their own |
| **Teams app** and channel publishing | Lets users chat in Teams | By hand. The installs stay in users' Teams after the environment is gone, pointing at nothing |
| Optional: workflows, triggers, Evaluate test sets | Tests and automation | By hand. A trigger on a published agent bills per run |

### Roles and local files

| Item | Why |
|---|---|
| Azure **Owner** (or Contributor plus User Access Administrator) on the subscription, an Entra admin role that can grant consent, **Power Platform Administrator** | Needed by whoever deploys. Granted by hand; revoke last ([Teardown](#teardown) step 10) |
| `terraform.tfvars`, Terraform state and backups, `.msal_cache.json`, the `vpn/` directory (secure) | Local to the deployer; not removed by a destroy |

## Stand up the stack

The order of operations for a new deployment. Profile differences: **secure** needs the VPN, and about
30 minutes after linking the enterprise policy before tool calls work; **rapid** is a public Basic v2
gateway, tested with Copilot Studio. Maker steps in the portals are in
[add-mcp-tool-to-agent.md](add-mcp-tool-to-agent.md). Pitfalls specific to AI coding agents are in
[AGENTS.md](../AGENTS.md).

### Sequence

1. **Accounts and licences.** Put the maker's **work** account in `maker_upn`. For the Microsoft Copilot
   harness, use a **Sandbox with pay-as-you-go**, never Developer. On a rebuild, clear or replace
   `copilot_connectors`: stale redirect or subject values cause `AADSTS50011`.
2. **Terraform.** Run `terraform -chdir=infra/profiles/<profile> apply -parallelism=1` for the first
   apply. The secure profile takes 1 to 1.5 hours (mostly API Management); the rapid profile about 11
   minutes. Plan to a file, read it, then apply that file; never chain plan and apply in one command.
3. **Backend, data, smoke.** Secure: `scripts/vpn.sh up` and open the deploy window first. Then
   `scripts/deploy-function.sh <profile>` (all three backends), `uv run scripts/sql-setup.py --profile <profile>`,
   `uv run scripts/sql-setup-budgeting.py --profile <profile>`, then
   `uv run scripts/smoke.py --profile <profile>` with `allow_test_sign_in=true`
   ([testing.md](testing.md)). Optional: `uv run scripts/mcp-client-once.py` proves MCP before Copilot
   Studio.
4. **Create the agent and register the MCP server** ([add-mcp-tool-to-agent.md](add-mcp-tool-to-agent.md)).
   Prefer Home → **Agent** (Microsoft Copilot harness); save until the URL has a bot ID. Add the MCP
   server with OAuth Manual and a **placeholder** client secret. Copy the redirect URL, then **Cancel**:
   don't create the connection yet.
5. **Managed identity on the connector.** Power Apps → Custom connectors → Security → Microsoft Entra ID →
   **Use managed identity**. Copy the subject after Update connector (exact string).
6. **Trust in Entra.** Put the redirect URL and subject in `copilot_connectors` (`terraform.tfvars`),
   plan and apply. Expect a federated identity credential to be created (and any replaced one
   destroyed), plus a swap of the connector ID in the data policy.
7. **Connection, then tool, then test.** Power Apps → Connections → **OAuth Connection** → Create
   (work-account sign-in) until the status is **Connected**. Only then add the tool on the agent and use
   Preview. Connecting before steps 5–6 fails with `AADSTS50011` or
   `ParameterNotDefined: Parameter 'token' is not allowed`.

### After stand-up

- Secure: if the enterprise policy was just linked, wait ~30 minutes before relying on tool calls.
- Baseline quality: seed an Evaluate test set and run the cheap containment probes (4, 6 and 8;
  [testing.md](testing.md#testing-the-agent-evaluations)). The smoke test proves the gateway, not the agent.
- Day-2 changes (new tools, users, agents): [operate.md](operate.md#tools-servers-and-agents).
- Give users the agent: [Make the agent available to users](#make-the-agent-available-to-users).
- Tear down: [Teardown](#teardown).

### Make the agent available to users

Verified on the Microsoft Copilot harness, rapid profile, in a new trial tenant.

1. In Copilot Studio, open the agent. **Channels → + → Teams + Microsoft 365.** Choose **Microsoft Teams only** (or
   Microsoft Copilot and Teams): the choice **cannot be changed after publishing**. Add the channel, then **Publish**
   again. The data policy in this repo already allows this channel; it blocks the demo website and Direct Line.
2. Open the channel → **Use and share → View in Microsoft Teams**. The install card shows the agent and its permissions.
   Press **Add**, then **Open**. The agent greets the user and the chat appears in their chat list.
3. Ask a question that needs a tool. The user sees streamed steps ("Calling directory_get_my_profile…") and then the
   answer. A user who has not connected to the tools yet is asked to sign in to each connection the first time.

**Starting a fresh conversation.** In Teams a user cannot: the agent's menu has only *About* and *Share app*, and typing
"Restart" or "Start over" does nothing (the agent still remembers earlier messages). Don't rely on users resetting a
thread between tasks; see [ai-safety.md](ai-safety.md#human-oversight) and
[AGENTS.md](../AGENTS.md#what-a-long-chat-costs-restart-and-monitor-2026-11-16).

**If Add fails** with "App package can't be uploaded. Unknown Exception", **wait and retry** (give a brand-new tenant a few
hours). In our run it worked on the third attempt about two hours after the channel was added, with no policy or role
change. Do not start changing tenant settings first. The Teams admin center ("setting up app management", Actions menus
greyed out) and the Microsoft 365 admin center (agent settings: "Error fetching settings") were still failing after the
install worked, and an end user does not need them. If you do reach those settings, the documented places are
Teams admin center → Manage apps → Org-wide app settings, and Microsoft 365 admin center → Agents → Settings. Agent settings
need an Entra role such as AI Administrator or Global Administrator, and **an admin portal won't sign in a consumer
(personal Microsoft account) login**, so keep a cloud-only admin user. More in
[AGENTS.md](../AGENTS.md#teams-and-workflows-what-we-learned-2026-11-16).

**No Teams?** A web page can talk to the agent with Microsoft's sample client:
[AGENTS.md](../AGENTS.md#calling-a-microsoft-copilot-harness-agent-from-your-own-web-page-2026-11-16).

## Teardown

Removing a deployment has an order. A plain `terraform destroy` fails partway on either profile and,
worse, can delete two service principals that belong to the whole tenant. Follow these steps.

[What gets created](#what-gets-created) lists every object. A destroy doesn't remove the billing plan,
the agent identities, the Teams installs, the auto-created Azure resources or the local files; steps 5, 8 and 9
cover them.

Run every command in the profile's directory (`terraform -chdir=infra/profiles/<profile> ...`). All
resource addresses are under `module.gateway`. Plan each destroy to a file, read it, then apply the
file.

| | Rapid profile | Secure profile |
|---|---|---|
| Steps | 3, 6 to 10 (and 4 and 5 if the environment has a billing plan; step 5 is never optional if a plan exists) | All |
| Time, as measured | About 10 minutes | About 35 minutes |

### Steps

1. **Disconnect the VPN** (secure profile): `scripts/vpn.sh down`.

2. **Unlink the enterprise policy first** (secure profile), while the environment still exists:

   ```bash
   terraform plan -destroy -target='module.gateway.powerplatform_enterprise_policy.network[0]' -out=unlink.tfplan
   terraform apply unlink.tfplan
   ```

   A linked policy can't be deleted, and an environment that has already been deleted can't be
   unlinked. If you are already in that state, see [recovery](#if-the-environment-was-deleted-first).

3. **Remove the tenant's own service principals from state.** Terraform adopts the tenant's Microsoft
   Graph and Azure SQL service principals to grant consent. Destroying them would delete them for every
   application in the tenant:

   ```bash
   terraform state rm module.gateway.azuread_service_principal.msgraph module.gateway.azuread_service_principal.azuresql
   ```

4. **If the environment has a billing plan, delete the environment in the Power Platform admin
   center**, not through Terraform (Manage → Environments → the environment → Delete). The provider
   calls a billing API first, which fails for an account that can't read the plan. Then remove it from
   state:

   ```bash
   terraform state rm module.gateway.powerplatform_managed_environment.agents module.gateway.powerplatform_environment.agents
   ```

   A Developer environment with no billing plan deletes cleanly through Terraform; skip this step.

5. **Delete the billing plan** (Licensing → Billing plans → select it → Delete billing plan) before the
   resource group goes. Terraform doesn't manage the plan, so a destroy never removes it. The plan's
   Power Platform account resource sits in the resource group, so deleting the group first leaves the
   plan in the admin center as "Disabled by linked resource", pointing at nothing. Always do this step
   when a billing plan was created for the deployment.

6. **Remove API Management's child resources from state.** Deleting them one by one through the
   management API times out (422); deleting the instance removes them anyway:

   ```bash
   terraform state list | grep -E 'azapi_resource\.mcp|azurerm_api_management_(api|api_policy|diagnostic|logger)\.' \
     | xargs -d '\n' terraform state rm
   ```

7. **Destroy:**

   ```bash
   terraform plan -destroy -refresh=false -out=destroy.tfplan
   terraform apply destroy.tfplan
   ```

8. **Expect the resource group to fail the first time.** Azure creates resources in it that Terraform
   doesn't know about. Delete them, then repeat step 7:

   - the "Failure Anomalies" smart detector alert rule (delete this first);
   - the "Application Insights Smart Detection" action group;
   - in the secure profile, the `NWTA-...` data collection rule and endpoint created by Traffic
     Analytics.

   `az resource list -g <resource group>` shows what is left.

9. **Check what survived.**

   | Check | Command |
   |---|---|
   | State is empty | `terraform state list` |
   | No resource group | `az group list --query "[?contains(name,'<prefix>')].name"` |
   | The billing plan is gone | Power Platform admin center → Licensing → Billing plans. Nothing listed, or none that you created for this deployment |
   | The data policy is gone | Power Platform admin center → Policies → Data policies. If it remains, delete it there |
   | The app registrations, the Finance Readers group and the tenant diagnostic setting are gone | Microsoft Entra admin center |
   | No agent identities are left from the deleted agents | Microsoft Entra admin center → Agent ID → Agent identities, or `az rest --method get --url "https://graph.microsoft.com/beta/servicePrincipals/microsoft.graph.agentIdentity?\$select=id,displayName,createdDateTime"`. Delete any whose agent no longer exists. Deleting an agent removes its agent identity, but destroying the environment around it did not: eight were left after earlier teardowns |

10. **Revoke any roles granted for the build last** (subscription Contributor, Power Platform
    Administrator). Steps 4 and 5 need them.

### What is left behind

- **Soft-deleted API Management instances.** They cost nothing and are purged automatically. To purge
  one now, or to reuse its name: `az apim deletedservice purge --service-name <name> --location <region>`.
- **`NetworkWatcherRG`**, which Azure creates for any virtual network. It is free, and Azure recreates
  it.
- **Local files:** the VPN profile and the `vpn/` directory, `terraform.tfvars`, and the token cache
  `.msal_cache.json`.

Destroying removes everything else Terraform created, including the Power Platform environment and the
agents, connectors and connections made in it by hand. It doesn't touch the maker's account or its
licences.

A published agent with a scheduled trigger is billed for every run. Delete the trigger when a test
ends, without waiting for teardown.

### If the environment was deleted first

If the environment was deleted while the enterprise policy was still linked, the policy can't be
deleted (`EnterprisePolicyDeleteNotAllowed`) and the deleted environment can't be unlinked
(`EnvironmentNotFound`). Recover the environment (admin center → Environments → Recently deleted),
unlink it, then delete it again:

```powershell
# Microsoft.PowerPlatform.EnterprisePolicies module
Disable-SubnetInjection -EnvironmentId "<environment ID>"
```

or the REST call, whose body needs the policy's `systemId` (from the Azure resource's
`properties.systemId`):

```http
POST https://api.bap.microsoft.com/providers/Microsoft.BusinessAppPlatform/environments/{environmentId}/enterprisePolicies/NetworkInjection/unlink?api-version=2019-10-01
{ "SystemId": "/regions/australia/providers/Microsoft.PowerPlatform/enterprisePolicies/{policyGuid}" }
```
