# Deploy

Everything needed to stand up a deployment, from accounts to agents, and to remove it again. The
sequence is in [Stand up the stack](#stand-up-the-stack); what must exist first is in
[Prerequisites](#prerequisites); removal is in [Teardown](#teardown). Maker steps in the Copilot Studio
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
may still say either. It is a Copilot Studio framework, not the GitHub Copilot service. **This
repository prefers it** once a Sandbox with pay-as-you-go is in place.

The gateway, the connector and the tools are the same for both.
[add-mcp-tool-to-agent.md](add-mcp-tool-to-agent.md) covers both; its screenshots show the Standard harness.

**An environment with no credits can't run a Microsoft Copilot harness agent.** The test pane answers "You
need credits to continue … This environment is out of credits" (`EnforcementUsageCredits`). A trial
environment has none. Event and scheduled triggers consume credits. They were tested only on the Standard
harness; unattended runs on the Microsoft Copilot harness have not been tested.

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
| **Maker credentials: end-user only** | An administrator, in the Power Platform admin center | Environment → Settings → Product → Features → Copilot Studio agents. Not done here ([governance.md](governance.md#known-governance-gaps)) |
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
| Explicit egress (NAT gateway or firewall) | New virtual networks have no default outbound internet access; API Management and the backend need Entra ID and Graph |

### 6. Identity configuration

All created by Terraform:

- The API app registration with the `Tools.Read` scope and admin-consented delegated permissions
  (Graph `User.Read`, Azure SQL `user_impersonation`).
- One app registration per agent, pre-authorised for `Tools.Read`.
- The app role `CostCentres.Read` on the API app, assigned to the maker (`cost_centres_user_upns`), and a
  user-assigned managed identity for the backend API, trusted by the API app as its credential.
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
   `scripts/deploy-function.sh <profile>`, `uv run scripts/sql-setup.py --profile <profile>`,
   `uv run scripts/smoke.py --profile <profile>` with `allow_test_sign_in=true`
   ([testing.md](testing.md)). Optional: `uv run scripts/mcp-client-once.py` proves MCP before Copilot
   Studio.
4. **Create the agent and register the MCP server** ([add-mcp-tool-to-agent.md](add-mcp-tool-to-agent.md)).
   Prefer Home → **Agent** (Microsoft Copilot harness); save until the URL has a bot ID. Add the MCP
   server with OAuth Manual and a **placeholder** client secret. Copy the redirect URL, then **Cancel**:
   don't create the connection yet.
5. **Managed identity on the connector.** Power Apps → Custom connectors → Security → Azure AD →
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
  [testing.md](testing.md#testing-the-agent-evals)). The smoke test proves the gateway, not the agent.
- Day-2 changes (new tools, users, agents): [operate.md](operate.md#tools-servers-and-agents).
- Tear down: [Teardown](#teardown).

## Teardown

Removing a deployment has an order. A plain `terraform destroy` fails partway on either profile and,
worse, can delete two service principals that belong to the whole tenant. Follow these steps.

Run every command in the profile's directory (`terraform -chdir=infra/profiles/<profile> ...`). All
resource addresses are under `module.gateway`. Plan each destroy to a file, read it, then apply the
file.

| | Rapid profile | Secure profile |
|---|---|---|
| Steps | 3, 6 to 10 (and 4 and 5 if the environment has a billing plan) | All |
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

5. **Delete the billing plan** (Licensing → Billing plans) before its resource group goes, or the plan
   is orphaned.

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
   | The data policy is gone | Power Platform admin center → Policies → Data policies. If it remains, delete it there |
   | The app registrations, the Finance Readers group and the tenant diagnostic setting are gone | Microsoft Entra admin center |

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
