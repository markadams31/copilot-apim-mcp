# Private networking

How to connect Copilot Studio agents to internal REST APIs, published as MCP tools through Azure API
Management, without any public data-plane endpoint on the API side. The page is general guidance;
callouts marked **In this demonstration** describe what this repository's **secure profile** deploys.
The rapid profile has none of this network (a public gateway, and SQL behind a firewall rule); it exists
for development only ([architecture.md](architecture.md#the-two-deployment-profiles)).

![Reference topology: Copilot Studio reaches an internal-mode API Management instance through a Power Platform delegated subnet; API Management reaches backends only through private endpoints; egress to Microsoft Entra ID and Microsoft Graph leaves through a hub firewall.](diagrams/networking-topology.svg)

<details>
<summary>Diagram description</summary>

On the left, a Microsoft cloud services box contains Copilot Studio (an agent in a Managed
Environment), Microsoft Entra ID and Microsoft Graph. Below it, a corporate network box contains
users, internal clients and corporate DNS. The primary Azure region contains an integration spoke
with two subnets: a Power Platform delegated subnet, where the connector runtime is injected, and an
API Management subnet with API Management in internal mode. A workload spoke contains an app
integration subnet for the backend's outbound traffic and a private endpoint subnet with private
endpoints for the API, SQL and Storage. The backend PaaS services sit outside the virtual networks
with public network access disabled, linked to their private endpoints by Private Link. A hub
virtual network contains Azure Firewall, an ExpressRoute or VPN gateway and a DNS Private Resolver;
private DNS zones are linked to every virtual network. The integration and workload spokes are
peered to the hub and directly to each other. A paired region holds a second Power Platform
delegated subnet, in a spoke joined to the integration spoke by global virtual network peering. A monitoring
box notes that Application Insights and Log Analytics ingest over public endpoints unless an Azure
Monitor Private Link Scope is used. Numbered blue arrows show the request path, orange arrows show
egress to Microsoft cloud services, and dashed grey arrows show DNS resolution.
</details>

## Walkthrough

1. **Users chat with the agent** in Teams, Microsoft 365 Copilot or a website. This traffic goes to
   Copilot Studio over the internet; Microsoft Entra ID sign-in and Conditional Access apply.
2. **The agent calls an MCP tool.** Copilot Studio runs the MCP connector in the environment's
   **delegated subnet** (Power Platform Virtual Network support), so the call to API Management's private IP
   address stays on your network. Only the connector's API calls use the subnet. OAuth sign-in and
   token requests go to Microsoft Entra ID directly.
3. **API Management calls the backend API** through the API's **private endpoint**. A network security group on the
   private endpoint subnet admits this traffic from API Management's subnet only, so nothing else on
   the network, VPN users included, can bypass API Management's authorisation.
4. **The backend API reaches its data** (SQL, Storage) through **virtual network integration** and the data
   services' private endpoints.
5. **Egress to Microsoft cloud services** (Microsoft Entra ID for token validation and on-behalf-of
   exchange, Microsoft Graph) leaves through the **hub firewall** with an FQDN allow-list. A route
   table sends 0.0.0.0/0 from the spokes to the firewall.
6. **Internal clients** (administrators, test tools, CI runners) reach API Management over
   ExpressRoute or VPN. The same per-agent authorisation applies to them.
7. **Name resolution:** private DNS zones are linked to every virtual network. Corporate DNS
   forwards those zones to the DNS Private Resolver's inbound endpoint, so on-premises clients
   resolve the same private addresses.

## Design decisions

### 1. How to make API Management private

| Option | Inbound | Outbound to private backends | Notes |
|---|---|---|---|
| **Premium (classic), internal virtual network mode** | Private IP only | Yes | The long-established enterprise pattern. Availability zones and multi-region. |
| **Premium v2, virtual network injection** | Private IP only | Yes | Newer platform. Injection can only be chosen **when the instance is created**. Check [regional availability](https://learn.microsoft.com/azure/api-management/api-management-region-availability): new instances are sometimes unavailable in a region because of capacity. |
| **Standard v2, private endpoint + virtual network integration** | Private endpoint, public access disabled | Yes | End-to-end isolation at a lower price than Premium. Public access can be disabled only after the private endpoint exists. |
| **Developer (classic), internal virtual network mode** | Private IP only | Yes | No SLA and a single unit. **For evaluation only.** |

Whichever you choose, internal-mode API Management needs:

- **A dedicated subnet with a network security group** that allows the management endpoint (TCP 3443 from the
  `ApiManagement` service tag) and the Azure load balancer (TCP 6390). See the
  [required network security group rules](https://learn.microsoft.com/azure/api-management/api-management-using-with-internal-vnet#configure-nsg-rules).
- **Its own DNS.** The gateway's name isn't published in public DNS. Create a private DNS zone
  **scoped to the instance's own FQDN** (for example `contoso-apim.azure-api.net`). **Never create a
  zone for `azure-api.net`**: it would take over name resolution for every other API Management
  instance, for everyone on your network.
- **A deployment path from inside the network.** CI/CD runners hosted on the internet can't reach
  an internal gateway. Use self-hosted runners in a peered virtual network.

> **In this demonstration:** Developer tier in internal mode, to keep the cost down. The rapid
> profile runs the same policies and MCP servers on **Basic v2** (public), and they behave the same,
> apart from approximate rate limits ([testing.md](testing.md)). **No private v2 option was tested.**

### 2. How Copilot Studio reaches API Management

Copilot Studio is a SaaS service. To call a private endpoint it needs **Power Platform virtual
network support**, which injects connector traffic into subnets you delegate. Requirements:

| Requirement | Detail |
|---|---|
| **Managed Environment** | The environment type must be Production, Sandbox, Developer or Default. Trial environments aren't supported. |
| **Two delegated subnets** | One in each Azure region of the environment's Power Platform geography. Australia, for example, needs **australiaeast and australiasoutheast**. Both must reach API Management (peering) and resolve its private name (DNS zone links). Either can carry the traffic: in this demonstration's Copilot Studio tests, calls came from the *secondary* region's subnet. |
| **Enterprise policy** | A `Microsoft.PowerPlatform/enterprisePolicies` resource of kind `NetworkInjection` naming both subnets, linked to the environment. If you linked it by hand, unlink it before teardown: a linked policy blocks deletion, and soft-deleting the environment first leaves an unlinkable orphan (see [deploy.md](deploy.md#teardown)). |
| **Licensing** | Users in the environment need an E5-class licence (Microsoft 365 E5, or E5 Compliance or Information Protection add-ons). See the [licensing FAQ](https://learn.microsoft.com/power-platform/admin/powerapps-flow-licensing-faq#azure-virtual-network-vnet). |
| **Connector support** | Custom connectors, which is what an MCP server in Copilot Studio is underneath, are supported. Connectors created **before** the environment was linked must be saved again. |
| **Change window** | Linking or unlinking a policy can cause up to 30 minutes of instability for connector traffic. |

**Global Secure Access for agents** is a complementary control, not an alternative. It sends the
agent's outbound traffic (HTTP nodes, custom connectors, MCP connectors) through Microsoft's Security
Service Edge, where web content, threat intelligence and file policies apply. Use it to restrict
what agents can reach on the internet; use Virtual Network support to reach private resources.

**Peering isn't transitive.** A spoke peered only to the hub can't reach another spoke. Either peer
the spokes that talk to each other directly (as the diagram shows: integration ↔ workload, and the
paired region's spoke ↔ integration), or send spoke-to-spoke traffic through the hub firewall with
route tables, which adds inspection at the cost of latency and firewall throughput.

> **In this demonstration:** delegated subnets in australiaeast (in the integration spoke) and
> australiasoutheast (a second, peered virtual network), and one `NetworkInjection` policy.

### 3. Backends reachable only from API Management

Authorisation is enforced in API Management. If an agent, or anyone holding an agent's token, can
reach a backend directly, that authorisation is bypassed. Make API Management the only route in:

- **Disable public network access** on every backend and data service, and reach them through
  **private endpoints**.
- **Put a network security group on the private endpoint subnet** and turn on private endpoint network policies.
  Without them, network security group rules don't apply to private endpoints and the whole virtual network can reach
  them. Allow only the flows each endpoint needs:

| Destination | Allowed source | Port |
|---|---|---|
| Backend API's private endpoint | API Management subnet | 443 |
| Data services' private endpoints (SQL, Storage) | The backend's virtual network integration subnet | 1433, 443 |
| Everything else | Denied | |

- **Keep the backend's own authentication on** (for example, App Service authentication validating
  the token's audience) as defence in depth. Don't re-implement per-agent rules in each backend.

> **In this demonstration:** a smoke test checks that the backend API's private endpoint drops
> traffic from VPN clients, and that its public endpoint returns 403.

### 4. Egress control

Virtual networks created with recent API versions have **no default outbound internet access**.
API Management, the backends and anything else that calls Microsoft Entra ID needs an explicit
route out:

- **Azure Firewall (recommended):** route 0.0.0.0/0 from the spokes to the hub firewall and allow
  only the FQDNs each workload needs. These include `login.microsoftonline.com` (token validation
  keys, on-behalf-of exchange), `graph.microsoft.com` and Application Insights ingestion endpoints,
  plus API Management's own dependencies (Azure Storage, Azure SQL, Azure Key Vault and Azure
  Monitor, by service tag). See API Management's
  [force-tunnelling guidance](https://learn.microsoft.com/azure/api-management/api-management-using-with-internal-vnet#force-tunnel-traffic-to-on-premises-firewall-using-expressroute-or-network-virtual-appliance).
- **NAT gateway (minimum):** a predictable public IP address, but no filtering.

> **In this demonstration:** a NAT gateway, to keep the cost down.

### 5. DNS

| Need | Approach |
|---|---|
| PaaS private endpoints | Private DNS zones per service (`privatelink.azurewebsites.net`, `privatelink.database.windows.net`, `privatelink.blob.core.windows.net` and so on), linked to every virtual network that resolves them. Usually centralised in the hub. |
| API Management (internal mode) | A private zone for the instance's own FQDN with an A record for its private IP address, linked to the integration spoke, the hub and **both** Power Platform delegated subnets' virtual networks. |
| On-premises clients | Conditional forwarders on corporate DNS to an **Azure DNS Private Resolver** inbound endpoint. |
| Power Platform delegated subnets | Resolve through their virtual network's DNS settings. The API Management zone must be linked to both virtual networks, or the connector can't find the gateway. |

> **In this demonstration:** a small VM running dnsmasq stands in for the DNS Private Resolver,
> and laptops on the point-to-site VPN use it for Azure names only.

### 6. Administrators and pipelines

- **Administrators and testers** reach API Management over ExpressRoute or site-to-site VPN. For
  remote individuals, point-to-site VPN with Microsoft Entra ID authentication, so Conditional
  Access applies.
- **Deployment pipelines** for API Management configuration and backend code run on self-hosted
  runners inside the network. With public access disabled, a backend can't accept a deployment
  from an internet-hosted runner.

> **In this demonstration:** point-to-site VPN with certificate authentication, and a Terraform
> variable that opens a temporary deployment window for the backend.

### 7. Monitoring the network

- **Virtual network flow logs** and **Azure Firewall logs** to a Log Analytics workspace: denied flows to
  private endpoints are an early sign of someone trying to bypass API Management.
- **DNS query logs** (DNS security policy) to spot lookups for private names from unexpected
  sources.
- **Telemetry ingestion is public by default.** Application Insights and Log Analytics accept
  data over public endpoints. To keep telemetry on private paths, use an
  [Azure Monitor Private Link Scope](https://learn.microsoft.com/azure/azure-monitor/logs/private-link-security).
  Per-call audit logging (user, agent, tool, decision) is built in the API policy; see
  [observability.md](observability.md) and
  [security.md](security.md#logging-without-leaking-data).

## Checklist

- [ ] API Management tier chosen for private inbound and outbound access, in a region where it can be created
- [ ] API Management subnet with the required network security group rules; private DNS zone scoped to the instance FQDN
- [ ] Power Platform Managed Environment with two delegated subnets in the geography's region pair, each able to reach and resolve API Management
- [ ] `NetworkInjection` enterprise policy linked to the environment; E5-class licences in place
- [ ] Public network access disabled on every backend and data service; private endpoints only
- [ ] Network security group on the private endpoint subnet allowing only API Management → API and backend → data
- [ ] Egress through a firewall with an FQDN allow-list (or a NAT gateway as a minimum)
- [ ] Spokes that talk to each other are peered directly, or routed through the hub firewall
- [ ] Private DNS zones linked to every virtual network; corporate DNS forwarding to a DNS Private Resolver
- [ ] Self-hosted CI/CD runners inside the network
- [ ] Virtual network flow logs and firewall logs collected; alerts on denied flows to private endpoints
- [ ] Azure Monitor Private Link Scope, if telemetry must stay on private paths

## Learn more

- [Use a virtual network with Azure API Management](https://learn.microsoft.com/azure/api-management/virtual-network-concepts)
- [Deploy API Management to an internal virtual network](https://learn.microsoft.com/azure/api-management/api-management-using-with-internal-vnet)
- [Network resource requirements for API Management injection](https://learn.microsoft.com/azure/api-management/virtual-network-injection-resources)
- [Inject a Premium v2 instance into a virtual network](https://learn.microsoft.com/azure/api-management/inject-vnet-v2)
- [Connect privately to API Management with an inbound private endpoint](https://learn.microsoft.com/azure/api-management/private-endpoint)
- [Azure API Management landing zone architecture](https://learn.microsoft.com/azure/architecture/example-scenario/integration/app-gateway-internal-api-management-function)
- [Virtual network support for Power Platform](https://learn.microsoft.com/power-platform/admin/vnet-support-overview)
- [Set up virtual network support for Power Platform](https://learn.microsoft.com/power-platform/admin/vnet-support-setup-configure)
- [Configure virtual network support for Copilot Studio agents](https://learn.microsoft.com/microsoft-copilot-studio/admin-network-isolation-vnet)
- [Custom connectors and virtual networks](https://learn.microsoft.com/connectors/custom-connectors/#virtual-network-support)
- [Secure Web and AI Gateway for Copilot Studio agents](https://learn.microsoft.com/power-platform/admin/security/secure-web-ai-gateway-agents)
- [Azure Functions networking options](https://learn.microsoft.com/azure/azure-functions/functions-networking-options)
- [Default outbound access in Azure](https://learn.microsoft.com/azure/virtual-network/ip-services/default-outbound-access)
- [Hub-spoke network topology in Azure](https://learn.microsoft.com/azure/architecture/networking/architecture/hub-spoke)
- [Use Azure Private Link to connect networks to Azure Monitor](https://learn.microsoft.com/azure/azure-monitor/logs/private-link-security)
- [What is Azure DNS Private Resolver?](https://learn.microsoft.com/azure/dns/dns-private-resolver-overview)
- [What is a private Azure DNS zone?](https://learn.microsoft.com/azure/dns/private-dns-privatednszone)
