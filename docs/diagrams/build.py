# /// script
# requires-python = ">=3.12"
# ///
"""Build the documentation diagrams as SVG, using Microsoft's official architecture icons.

    uv run docs/diagrams/build.py          # writes docs/diagrams/*.svg

Conventions follow Microsoft's guidance for architecture diagrams (Well-Architected Framework,
"Architecture design diagrams"): official icons with the product name beside them, directional
single-headed arrows, numbered flows that match the text, PaaS services drawn outside the virtual
network with only their private endpoints inside, a legend, and title/date metadata.

Icons are in icons/ (a subset of the official Azure, Power Platform and Microsoft Entra icon
sets, used under Microsoft's terms for architecture diagrams; see icons/NOTICE.md).
"""

from __future__ import annotations

import base64
import html
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).parent
ICONS = HERE / "icons"
UPDATED = "2026-11-09"
NEW = "2026-11-12"  # diagrams written or changed on this date
NEWER = "2026-11-13"  # diagrams redrawn for the three-system scenario
FONT = "'Segoe UI', 'Helvetica Neue', Arial, sans-serif"

# Palette: Microsoft Fluent neutrals plus a few semantic colours. Every colour is paired with a
# line pattern or a label, so nothing relies on colour alone.
INK = "#201F1E"
MUTED = "#605E5C"
BLUE = "#0078D4"  # request path
ORANGE = "#CA5010"  # egress to Microsoft cloud services
GREEN = "#498205"  # virtual networks
GREY = "#8A8886"
PURPLE = "#8764B8"  # tokens issued by Microsoft Entra ID
RED = "#C50F1F"  # refused requests
MONO = "Consolas, 'Cascadia Mono', Menlo, monospace"

GROUP_STYLE = {
    #           fill        stroke    dash     width
    "region": ("#FAFAFA", GREY, "8 5", 1.5),
    "cloud": ("#F3F2F1", MUTED, None, 1.2),
    "onprem": ("#FFF9F0", "#8E562E", None, 1.2),
    "vnet": ("#F4F9F0", GREEN, None, 1.5),
    "subnet": ("#FFFFFF", GREEN, "4 3", 1.2),
    "plain": ("#FFFFFF", GREY, None, 1.0),
}


def _icon_href(name: str) -> str:
    data = (ICONS / f"{name}.svg").read_bytes()
    return "data:image/svg+xml;base64," + base64.b64encode(data).decode()


def _esc(s: str) -> str:
    return html.escape(s, quote=True)


@dataclass
class Box:
    x: float
    y: float
    w: float
    h: float

    @property
    def cx(self):
        return self.x + self.w / 2

    @property
    def cy(self):
        return self.y + self.h / 2

    @property
    def top(self):
        return (self.cx, self.y)

    @property
    def bottom(self):
        return (self.cx, self.y + self.h)

    @property
    def left(self):
        return (self.x, self.cy)

    @property
    def right(self):
        return (self.x + self.w, self.cy)


class Diagram:
    def __init__(
        self, w: int, h: int, title: str, subtitle: str, updated: str | None = None
    ):
        self.w, self.h = w, h
        self.back: list[str] = []  # groups
        self.mid: list[str] = []  # lines
        self.front: list[str] = []  # nodes, badges, labels
        self.colors: set[str] = set()
        self._text(24, 38, title, 22, weight="600", layer=self.front)
        self._text(
            24,
            62,
            f"{subtitle}  ·  Last updated {updated or UPDATED}",
            13,
            MUTED,
            layer=self.front,
        )

    # -- primitives ------------------------------------------------------------------------------

    def _text(
        self, x, y, s, size=13, color=INK, weight="400", anchor="start", layer=None
    ):
        lines = s.split("\n")
        out = []
        for i, line in enumerate(lines):
            out.append(
                f'<text x="{x}" y="{y + i * (size + 3)}" font-family="{FONT}" font-size="{size}" '
                f'fill="{color}" font-weight="{weight}" text-anchor="{anchor}">{_esc(line)}</text>'
            )
        (layer if layer is not None else self.front).extend(out)

    def group(self, x, y, w, h, label, kind="plain", icon=None, sublabel=None) -> Box:
        fill, stroke, dash, sw = GROUP_STYLE[kind]
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.back.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" '
            f'stroke="{stroke}" stroke-width="{sw}"{d}/>'
        )
        tx = x + 10
        if icon:
            self.back.append(
                f'<image href="{_icon_href(icon)}" x="{x + 8}" y="{y + 7}" width="20" height="20"/>'
            )
            tx = x + 34
        self._text(tx, y + 22, label, 13, INK, "600", layer=self.back)
        if sublabel:
            self._text(tx, y + 38, sublabel, 11, MUTED, layer=self.back)
        return Box(x, y, w, h)

    def node(self, cx, cy, icon, label, sub=None, size=44, pos="below") -> Box:
        """An official icon with its name. pos='right' keeps the space below free for arrows."""
        x, y = cx - size / 2, cy - size / 2
        self.front.append(
            f'<image href="{_icon_href(icon)}" x="{x}" y="{y}" width="{size}" height="{size}"/>'
        )
        n = label.count("\n") + 1
        if pos == "right":
            lines = n + (sub.count("\n") + 1 if sub else 0)
            ty = cy - (lines * 15) / 2 + 11
            self._text(x + size + 8, ty, label, 12.5, INK, "600")
            if sub:
                self._text(x + size + 8, ty + n * 15.5, sub, 11, MUTED)
        else:
            self._text(cx, cy + size / 2 + 16, label, 12.5, INK, "600", "middle")
            if sub:
                self._text(
                    cx, cy + size / 2 + 16 + n * 15.5, sub, 11, MUTED, anchor="middle"
                )
        return Box(x, y, size, size)

    def service(self, cx, cy, w, h, label, sub=None, dashed=False) -> Box:
        """A tile for something with no official icon (a service, an MCP server, an API)."""
        x, y = cx - w / 2, cy - h / 2
        da = ' stroke-dasharray="5 3"' if dashed else ""
        self.front.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="4" fill="#FFFFFF" '
            f'stroke="{MUTED}" stroke-width="1.2"{da}/>'
        )
        n1 = label.count("\n") + 1
        n2 = (sub.count("\n") + 1) if sub else 0
        top = cy - (n1 * 15.5 + n2 * 14) / 2 + 11
        self._text(cx, top, label, 12.5, INK, "600", "middle")
        if sub:
            self._text(cx, top + n1 * 15.5, sub, 11, MUTED, anchor="middle")
        return Box(x, y, w, h)

    def chip(self, cx, cy, text, w=110, color=BLUE) -> Box:
        """A tool name, as listed by an MCP server."""
        x, y = cx - w / 2, cy - 13
        self.front.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="26" rx="13" fill="#EFF6FC" '
            f'stroke="{color}" stroke-width="1.2"/>'
            f'<text x="{cx}" y="{cy + 4.5}" font-family="{MONO}" font-size="12" fill="{INK}" '
            f'text-anchor="middle">{_esc(text)}</text>'
        )
        return Box(x, y, w, 26)

    def code(self, x, y, w, h, title, lines):
        """A configuration excerpt."""
        self.front.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="#FAF9F8" '
            f'stroke="{GREY}" stroke-width="1"/>'
        )
        self._text(x + 12, y + 22, title, 12.5, INK, "600")
        for i, line in enumerate(lines):
            self.front.append(
                f'<text x="{x + 16}" y="{y + 46 + i * 18}" font-family="{MONO}" font-size="12.5" '
                f'fill="{INK}" xml:space="preserve">{_esc(line)}</text>'
            )
        return Box(x, y, w, h)

    def refused(self, x, y, text, anchor="start"):
        """Where a refused request stops: a red cross and the outcome."""
        self.front.append(
            f'<circle cx="{x}" cy="{y}" r="10" fill="#FFFFFF" stroke="{RED}" stroke-width="2"/>'
            f'<path d="M {x - 4.5} {y - 4.5} L {x + 4.5} {y + 4.5} M {x + 4.5} {y - 4.5} '
            f'L {x - 4.5} {y + 4.5}" stroke="{RED}" stroke-width="2.2"/>'
        )
        dx = 16 if anchor == "start" else -16
        self._label(x + dx, y + 4, text, RED, anchor)

    def _marker(self, color):
        self.colors.add(color)
        return f"url(#arrow-{color.lstrip('#')})"

    def arrow(
        self,
        pts,
        color=BLUE,
        dash=None,
        head=True,
        width=2.0,
        label=None,
        at=None,
        anchor="start",
        num=None,
        num_at=None,
    ):
        d = "M " + " L ".join(f"{x} {y}" for x, y in pts)
        attrs = f'fill="none" stroke="{color}" stroke-width="{width}"'
        if dash:
            attrs += f' stroke-dasharray="{dash}"'
        if head:
            attrs += f' marker-end="{self._marker(color)}"'
        self.mid.append(f'<path d="{d}" {attrs} stroke-linejoin="round"/>')
        if label:
            lx, ly = at
            self._label(lx, ly, label, color, anchor)
        if num is not None:
            self.badge(*(num_at or pts[0]), num, color)

    def _label(self, x, y, s, color, anchor="start"):
        lines = s.split("\n")
        width = max(len(line) for line in lines) * 6.1 + 8
        height = len(lines) * 14 + 4
        bx = x - (
            width / 2 if anchor == "middle" else (width if anchor == "end" else 0)
        )
        self.front.append(
            f'<rect x="{bx - 2}" y="{y - 12}" width="{width}" height="{height}" rx="3" '
            f'fill="#FFFFFF" fill-opacity="0.92"/>'
        )
        for i, line in enumerate(lines):
            self.front.append(
                f'<text x="{x}" y="{y + i * 14}" font-family="{FONT}" font-size="11" '
                f'fill="{color}" text-anchor="{anchor}">{_esc(line)}</text>'
            )

    def badge(self, x, y, n, color=BLUE):
        self.front.append(
            f'<circle cx="{x}" cy="{y}" r="11" fill="{color}" stroke="#FFFFFF" stroke-width="2"/>'
            f'<text x="{x}" y="{y + 4.5}" font-family="{FONT}" font-size="12" font-weight="700" '
            f'fill="#FFFFFF" text-anchor="middle">{n}</text>'
        )

    def legend(self, x, y, items, width=300):
        """items: (kind, colour, dash, text); kind is 'line' or 'box'."""
        h = 30 + 22 * len(items)
        self.front.append(
            f'<rect x="{x}" y="{y}" width="{width}" height="{h}" rx="6" fill="#FFFFFF" '
            f'stroke="{GREY}" stroke-width="1"/>'
        )
        self._text(x + 12, y + 20, "Legend", 12.5, INK, "600")
        for i, (kind, color, dash, text) in enumerate(items):
            iy = y + 40 + i * 22
            if kind == "line":
                da = f' stroke-dasharray="{dash}"' if dash else ""
                mk = f' marker-end="{self._marker(color)}"' if dash != "peer" else ""
                da = ' stroke-dasharray="7 4"' if dash == "peer" else da
                self.front.append(
                    f'<path d="M {x + 14} {iy - 4} L {x + 58} {iy - 4}" stroke="{color}" '
                    f'stroke-width="2" fill="none"{da}{mk}/>'
                )
            elif kind == "box":
                fill, stroke, bdash, _ = GROUP_STYLE[color]
                da = f' stroke-dasharray="{bdash}"' if bdash else ""
                self.front.append(
                    f'<rect x="{x + 14}" y="{iy - 12}" width="44" height="16" rx="3" '
                    f'fill="{fill}" stroke="{stroke}"{da}/>'
                )
            elif kind == "badge":
                self.badge(x + 36, iy - 4, "1", color)
            self._text(x + 70, iy, text, 11.5, INK)

    def save(self, name: str):
        markers = "".join(
            f'<marker id="arrow-{c.lstrip("#")}" viewBox="0 0 10 10" refX="9" refY="5" '
            f'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
            f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{c}"/></marker>'
            for c in sorted(self.colors)
        )
        svg = (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" '
            f'width="{self.w}" height="{self.h}" role="img">'
            f"<defs>{markers}</defs>"
            f'<rect width="{self.w}" height="{self.h}" fill="#FFFFFF"/>'
            + "".join(self.back + self.mid + self.front)
            + "</svg>"
        )
        (HERE / f"{name}.svg").write_text(svg)
        print(f"wrote {name}.svg")


# =================================================================================================
# Diagrams
# =================================================================================================


def networking_topology():
    d = Diagram(
        1850,
        1030,
        "Private networking for Copilot Studio agents using MCP tools in API Management",
        "Reference topology: hub and spoke",
    )

    # -- Left column: Microsoft cloud services, and the corporate network --------------------
    d.group(
        24,
        96,
        240,
        474,
        "Microsoft cloud services",
        "cloud",
        sublabel="SaaS, public endpoints",
    )
    cs = d.node(
        144, 196, "copilot-studio", "Copilot Studio", "Agent in a Managed\nEnvironment"
    )
    entra = d.node(144, 346, "entra-id", "Microsoft Entra ID", "Sign-in, tokens, OBO")
    graph = d.service(144, 500, 196, 50, "Microsoft Graph", "and other Microsoft APIs")

    d.group(
        24,
        600,
        240,
        400,
        "Corporate network",
        "onprem",
        sublabel="Offices and VPN users",
    )
    users = d.node(144, 690, "users", "Users")
    clients = d.node(144, 810, "vm", "Internal clients", "Admin, test, CI runners")
    corp_dns = d.service(144, 940, 196, 50, "Corporate DNS", "Conditional forwarders")

    # -- Primary region ---------------------------------------------------------------------
    d.group(
        290,
        96,
        1230,
        908,
        "Azure region (primary)",
        "region",
        sublabel="Workload endpoints are private",
    )

    # Integration spoke: where agents' tool calls arrive
    d.group(316, 150, 584, 270, "Integration spoke virtual network", "vnet", "vnet")
    d.group(336, 196, 260, 204, "Power Platform delegated subnet", "subnet", "subnet")
    pp = d.node(
        380,
        300,
        "power-platform",
        "Connector runtime",
        "Injected by Power\nPlatform VNet support",
        pos="right",
    )
    d.group(620, 196, 260, 204, "API Management subnet", "subnet", "subnet")
    apim = d.node(
        670,
        300,
        "apim",
        "API Management",
        "Internal mode:\nMCP servers, REST APIs",
        pos="right",
    )

    # Workload spoke: the backend's outbound integration, and private endpoints
    d.group(930, 150, 330, 460, "Workload spoke virtual network", "vnet", "vnet")
    d.group(950, 196, 290, 140, "App integration subnet", "subnet", "subnet")
    integ = d.node(
        1010,
        270,
        "subnet",
        "VNet integration",
        "Backend outbound traffic",
        size=32,
        pos="right",
    )
    d.group(
        950,
        356,
        290,
        234,
        "Private endpoint subnet",
        "subnet",
        "subnet",
        "NSG: only the flows each endpoint needs",
    )
    pe_api = d.node(980, 490, "private-endpoint", "API", size=36, pos="right")
    pe_sql = d.node(1075, 490, "private-endpoint", "SQL", size=36, pos="right")
    pe_st = d.node(1170, 490, "private-endpoint", "Storage", size=36, pos="right")

    # Backend PaaS: outside the VNets, reached only through their private endpoints
    d.group(
        930,
        640,
        330,
        190,
        "Backend services (PaaS)",
        "plain",
        sublabel="Public network access disabled",
    )
    api = d.node(980, 740, "function", "Backend", "Functions,\nApp Service")
    sql = d.node(1075, 740, "sql", "Azure SQL")
    st = d.node(1170, 740, "storage", "Storage")

    # Hub: shared connectivity, egress and DNS
    d.group(
        316,
        640,
        444,
        340,
        "Hub virtual network",
        "vnet",
        "vnet",
        "Shared connectivity and egress",
    )
    fw = d.node(372, 720, "firewall", "Azure Firewall", "FQDN allow-list", pos="right")
    gw = d.node(
        600, 810, "vpn-gateway", "Virtual network gateway", "ExpressRoute or VPN"
    )
    res = d.node(
        420,
        900,
        "dns-resolver",
        "DNS Private Resolver",
        "Inbound endpoint",
        pos="right",
    )
    zones = d.node(
        845, 900, "dns-zone", "Private DNS zones", "Global, linked to\nevery VNet"
    )

    # Monitoring: off the request path
    d.group(
        1300,
        150,
        200,
        300,
        "Monitoring",
        "plain",
        sublabel="Public ingestion unless you\nuse Azure Monitor Private\nLink Scope",
    )
    d.node(1400, 270, "app-insights", "Application Insights")
    d.node(1400, 380, "log-analytics", "Log Analytics", "Resource and flow logs")

    # -- Paired region: the second Power Platform delegated subnet ----------------------------
    d.group(
        1544,
        640,
        290,
        360,
        "Azure region (paired)",
        "region",
        sublabel="Same Power Platform geography",
    )
    d.group(1564, 700, 250, 280, "Spoke virtual network", "vnet", "vnet")
    d.group(1584, 746, 210, 214, "Power Platform\ndelegated subnet", "subnet", "subnet")
    d.node(1689, 870, "power-platform", "Connector runtime", "Same enterprise policy")

    # -- Flows -----------------------------------------------------------------------------
    # 1  Users chat with the agent over the internet (Entra sign-in, Conditional Access)
    d.arrow([users.left, (44, 690), (44, 196), cs.left], num=1, num_at=(44, 585))
    # 2  The agent's MCP tool call runs in the delegated subnet and reaches APIM privately
    d.arrow([cs.right, (304, 196), (304, 300), pp.left], num=2, num_at=(304, 250))
    d.arrow([(552, 300), apim.left], label="HTTPS 443", at=(560, 290))
    # 3  APIM calls the internal API through the API's private endpoint
    d.arrow([apim.bottom, (670, 490), pe_api.left], num=3, num_at=(800, 490))
    # 4  The API reaches its data through VNet integration and private endpoints
    d.arrow(
        [
            api.left,
            (944, 740),
            (944, 850),
            (1280, 850),
            (1280, 236),
            (1010, 236),
            integ.top,
        ],
        num=4,
        num_at=(1280, 600),
    )
    d.arrow([integ.left, (962, 270), (962, 432), (1075, 432), pe_sql.top])
    d.arrow([(1075, 432), (1170, 432), pe_st.top], label="1433 · 443", at=(1092, 424))
    # Private Link from each private endpoint to its service
    for pe, svc in ((pe_api, api), (pe_sql, sql), (pe_st, st)):
        d.arrow([pe.bottom, svc.top], color=GREY, dash="3 3")
    d._label(1095, 628, "Private Link", GREY, "middle")
    # 5  Egress to Entra ID and Graph (token validation, OBO) leaves through the firewall
    d.arrow(
        [fw.left, (276, 720), (276, 346), entra.right],
        color=ORANGE,
        num=5,
        num_at=(276, 650),
    )
    d.arrow([(276, 480), (276, 500), graph.right], color=ORANGE)
    d._label(402, 758, "UDR 0.0.0.0/0 from the spokes", ORANGE, "start")
    d._label(256, 418, "login.microsoftonline.com\ngraph.microsoft.com", ORANGE, "end")
    # 6  Internal clients reach APIM over ExpressRoute or VPN
    d.arrow([clients.right, gw.left], num=6, num_at=(300, 810))
    d.arrow([gw.top, (600, 440), (692, 440), (692, 322)])
    # 7  Corporate DNS forwards the private zones to the resolver's inbound endpoint
    d.arrow(
        [corp_dns.right, (300, 940), (300, 900), res.left],
        color=MUTED,
        dash="6 4",
        num=7,
        num_at=(300, 965),
    )
    d.arrow([(res.x + 44 + 150, 900), zones.left], color=MUTED, dash="6 4")
    # VNet peering: links, not flows
    d.arrow([(500, 420), (500, 640)], color=GREEN, dash="7 4", head=False, width=3)
    d._label(506, 540, "VNet peering", GREEN)
    d.arrow(
        [(760, 690), (915, 690), (915, 600), (930, 600)],
        color=GREEN,
        dash="7 4",
        head=False,
        width=3,
    )
    # Peering isn't transitive, so spokes that talk to each other are peered directly
    # (the alternative is routing spoke-to-spoke traffic through the hub firewall).
    d.arrow([(900, 380), (930, 380)], color=GREEN, dash="7 4", head=False, width=3)
    d._label(904, 404, "VNet\npeering", GREEN)
    d.arrow(
        [(1790, 700), (1790, 620), (1530, 620), (1530, 141), (860, 141), (860, 150)],
        color=GREEN,
        dash="7 4",
        head=False,
        width=3,
    )
    d._label(1180, 135, "Global VNet peering to the integration spoke", GREEN, "middle")

    d.legend(
        1544,
        96,
        [
            ("line", BLUE, None, "Request path"),
            ("line", ORANGE, None, "Egress to Microsoft cloud services"),
            ("line", MUTED, "6 4", "DNS resolution"),
            ("line", GREY, "3 3", "Private Link to a PaaS service"),
            ("line", GREEN, "peer", "VNet peering (a link, not a flow)"),
            ("box", "vnet", None, "Virtual network"),
            ("box", "subnet", None, "Subnet"),
            ("badge", BLUE, None, "Step in the walkthrough"),
        ],
        width=290,
    )
    d.save("networking-topology")


def solution_architecture():
    d = Diagram(
        1650,
        900,
        "Copilot Studio agents using internal REST APIs as MCP tools through API Management",
        "Solution architecture",
        NEWER,
    )

    # Identity across the top: every hop is authorised by Microsoft Entra ID
    d.group(
        140,
        96,
        1040,
        112,
        "Microsoft Entra ID",
        "cloud",
        "entra-id",
        "Issues every token; Conditional Access applies to users",
    )
    d.service(
        380,
        160,
        230,
        44,
        "Agent client apps",
        "one per agent; used by all its connections",
    )
    d.service(
        640,
        160,
        230,
        44,
        "API app registration",
        "scope Tools.Read, role CostCentres.Read",
    )
    d.service(905, 160, 230, 44, "Delegated permissions", "Graph, SQL (admin consent)")

    users = d.node(70, 430, "users", "Users", "Teams, or the\nCopilot Studio test pane")

    # Copilot Studio
    d.group(
        140,
        240,
        310,
        420,
        "Microsoft Copilot Studio",
        "cloud",
        "copilot-studio",
        "Managed Environment\nData policies",
    )
    d.node(
        340,
        395,
        "copilot-studio",
        "Employee Assistant",
        "MCP connection:\nOAuth as the user",
    )
    d.node(
        340,
        555,
        "copilot-studio",
        "Finance Assistant",
        "MCP connection:\nOAuth as the user",
    )

    # Private network: API Management, internal APIs, internal data
    d.group(
        480,
        240,
        790,
        420,
        "Private network (secure profile)",
        "region",
        sublabel="Reached through a Power Platform delegated subnet; no public endpoints",
    )
    d.group(
        500,
        300,
        380,
        340,
        "Azure API Management",
        "plain",
        "apim",
        "One MCP server per business domain; one policy for every path",
    )
    mcp_a = d.service(
        600,
        385,
        180,
        72,
        "Directory MCP server",
        "both agents\ntool:\ndirectory_get_my_profile",
    )
    mcp_b = d.service(
        600,
        510,
        180,
        168,
        "Finance MCP server",
        "Finance Assistant only\ntools:\nfinance_list_cost_centres,\nfinance_query_spend,\nbudgeting_get_forecast,\nbudgeting_update_…",
    )
    rest = d.service(
        790,
        470,
        150,
        150,
        "REST APIs",
        "finance +\nbudgeting\nimports\n\nValidate token\nAllow-list\nForward token",
    )
    d.group(
        910,
        300,
        190,
        340,
        "Backend systems",
        "plain",
        sublabel="Private endpoints only",
    )
    fn = d.node(
        1040,
        410,
        "function",
        "Directory + finance API",
        "Spend and directory: OBO\nCost centres: app-only",
    )
    fn2 = d.node(
        1040,
        550,
        "function",
        "Budgeting API",
        "Forecast read and update\n(the only write), OBO",
    )
    sql = d.node(
        1195,
        430,
        "sql",
        "Finance database",
        "Spend as the user;\ncost centres as the API",
    )
    sql2 = d.node(
        1195,
        570,
        "sql",
        "Budgeting database",
        "Budget Editors only;\nrecords the writer",
    )

    graph = d.service(
        1440, 300, 220, 54, "Microsoft Graph", "Returns only the user's data"
    )

    # Observability across the bottom
    d.group(
        140,
        700,
        1130,
        170,
        "Observability",
        "plain",
        "monitor",
        "One Log Analytics workspace; correlate by user, agent and tool",
    )
    d.node(
        300,
        800,
        "app-insights",
        "Application Insights",
        "Copilot Studio agent spans,\ngateway MCP telemetry",
        pos="right",
    )
    d.node(
        700,
        800,
        "log-analytics",
        "Log Analytics",
        "Gateway logs, backend\ntraces, flow logs",
        pos="right",
    )
    d.service(1100, 800, 220, 54, "Entra sign-in logs", "users, agents, OBO exchanges")

    # 1 Users chat with an agent
    d.arrow([users.right, (140, 430)], num=1, num_at=(118, 430))
    # 2 The agent's connection gets a user token for the API
    d.arrow(
        [(340, 208), (340, 373)], color=PURPLE, dash="6 3", num=2, num_at=(340, 232)
    )
    d._label(
        330,
        316,
        "User token\naud = API\nazp = agent app\nscp = Tools.Read",
        PURPLE,
        "end",
    )
    # 3 The agent calls its own MCP server
    d.arrow([(362, 395), (450, 395), (450, 385), mcp_a.left], num=3, num_at=(470, 385))
    d.arrow([(362, 555), mcp_b.left])
    d.arrow([(362, 535), (420, 535), (420, 405), (510, 405)])
    # 4 APIM maps the tool to a REST operation, authorises it, forwards it privately
    d.arrow([mcp_a.right, (700, 385), (700, 430), rest.left[0:1] + (430,)])
    d.arrow([mcp_b.right, (700, 555), (700, 510), (715, 510)])
    d.arrow([rest.right, (890, 470), (890, 410), fn.left], num=4, num_at=(890, 470))
    d.arrow([(890, 470), (890, 550), fn2.left])
    # 5 The API exchanges the token on-behalf-of the user, then reads data as the user
    d.arrow(
        [(1040, 388), (1040, 208)], color=PURPLE, dash="6 3", num=5, num_at=(1040, 270)
    )
    d._label(1048, 352, "On-behalf-of\nexchange", PURPLE)
    d.arrow([(1062, 410), (1150, 410), (1150, 430), sql.left])
    d.arrow([(1150, 410), (1150, 300), graph.left])
    d.arrow([fn2.right, (1150, 550), (1150, 570), sql2.left])
    d._label(1335, 350, "As the user, through\ncontrolled egress", BLUE)
    # 6 Every layer reports to one workspace
    for x in (295, 690, 1040):
        d.arrow([(x, 660), (x, 700)], color=GREY, dash="3 3")
    d.badge(690, 680, 6, GREY)

    d.legend(
        1310,
        420,
        [
            ("line", BLUE, None, "Request path"),
            ("line", PURPLE, "6 3", "Token issued by Microsoft Entra ID"),
            ("line", GREY, "3 3", "Telemetry"),
            ("box", "region", None, "Private network boundary"),
            ("badge", BLUE, None, "Step in the walkthrough"),
        ],
        width=320,
    )
    d.save("solution-architecture")


def two_front_doors():
    d = Diagram(
        1500,
        800,
        "One REST API, two front doors: why authorisation belongs on the API",
        "Each refused path is a smoke-test check (3, 7 and 8)",
        NEWER,
    )
    agent = d.node(
        120,
        230,
        "copilot-studio",
        "Employee Assistant",
        "Token issued to\nits client app",
    )
    client = d.node(
        120,
        520,
        "vm",
        "Any client holding\nthat token",
        "a script, or a misused\nconnection",
    )

    d.group(
        300,
        100,
        720,
        600,
        "Azure API Management",
        "plain",
        "apim",
        "The REST API is imported once and exposed twice",
    )
    d.group(
        320,
        160,
        260,
        320,
        "Front door 1: MCP servers",
        "cloud",
        sublabel="One per business domain",
    )
    mcp_a = d.service(
        450,
        250,
        220,
        70,
        "Directory MCP server",
        "/directory-mcp/mcp\nPolicy: both agents' apps",
    )
    mcp_b = d.service(
        450,
        390,
        220,
        70,
        "Finance MCP server",
        "/finance-mcp/mcp\nPolicy: Finance app only",
    )
    d.group(
        620,
        160,
        380,
        520,
        "Front door 2: REST API",
        "cloud",
        sublabel="/tools/* (imported from OpenAPI)",
    )
    pol = d.service(
        810,
        285,
        340,
        106,
        "API policy: runs on every path",
        "1. Validate token: tenant, audience, Tools.Read\n2. Allow-list: operation + agent\n3. Deny anything not on the list",
    )
    ops = [
        d.service(810, y, 300, 44, f"GET {path}", f"tool: {tool}")
        for y, path, tool in (
            (440, "/directory/me", "directory_get_my_profile"),
            (500, "/finance/cost-centres", "finance_list_cost_centres"),
            (560, "/finance/spend", "finance_query_spend"),
            (620, "/diagnostics/caller", "none (smoke test only)"),
        )
    ]

    d.group(
        1060,
        160,
        400,
        480,
        "Backend",
        "plain",
        sublabel="Private endpoint; public access disabled",
    )
    fn = d.node(1300, 440, "function", "Backend API")
    nsg = d.node(
        1140,
        580,
        "nsg",
        "NSG",
        "Private endpoint subnet:\nAPI Management only",
        pos="right",
    )

    # Allowed: the Employee Assistant calls its own server, the tool maps to an operation it may use
    d.arrow([agent.right, (250, 230), (250, 250), mcp_a.left], num=1, num_at=(290, 250))
    d.arrow([mcp_a.right, (600, 250), (600, 262), pol.left])
    d.arrow([(900, 338), (900, 418)])
    d.arrow(
        [ops[0].right, (1100, 440), fn.left],
        label="via the private endpoint",
        at=(1104, 430),
    )
    d._label(30, 188, "✓ tools/call directory_get_my_profile", BLUE)

    # Refused 1: the Employee Assistant's token on the Finance MCP server
    d.arrow(
        [(142, 245), (230, 245), (230, 390), mcp_b.left],
        color=RED,
        dash="6 3",
        num=2,
        num_at=(230, 320),
    )
    d.refused(350, 430, "401: not an agent that uses this server", "start")

    # Refused 2: skipping the MCP server and calling the REST API directly
    d.arrow(
        [client.right, (600, 520), (600, 312), pol.left],
        color=RED,
        dash="6 3",
        num=3,
        num_at=(400, 520),
    )
    d.refused(650, 370, "403: finance_query_spend isn't on its list", "start")
    d._label(170, 546, "GET /tools/finance/spend?... with its token", RED)

    # Refused 3: skipping API Management altogether
    d.arrow(
        [client.left, (60, 520), (60, 740), (1140, 740), nsg.bottom],
        color=RED,
        dash="6 3",
        num=4,
        num_at=(400, 740),
    )
    d.refused(1140, 680, "Dropped: not from API Management", "start")
    d._label(
        600,
        734,
        "GET https://<backend>/api/finance/spend?... with its token",
        RED,
        "middle",
    )

    d.legend(
        1220,
        40,
        [
            ("line", BLUE, None, "Allowed"),
            ("line", RED, "6 3", "Refused (outcome marked ✗)"),
            ("badge", BLUE, None, "Path in the text"),
        ],
        width=240,
    )
    d.save("rest-api-two-front-doors")


def agent_tool_access():
    d = Diagram(
        1500,
        1020,
        "Domain MCP servers, shared across agents",
        "Four questions, answered at four layers (finance + budgeting behind one gateway)",
        NEWER,
    )
    heads = [
        (120, "Which agent?", "Its own client app, accepted\nby the servers it uses"),
        (440, "Which tools?", "Each server lists its tools\nto the agents that use it"),
        (
            855,
            "Which operation?",
            "The API policy's allow-list,\nchecked on every path",
        ),
        (1300, "Which data?", "As the user (delegated)\nor as the app (app-only)"),
    ]
    for x, h, sub in heads:
        d._text(x, 104, h, 15, BLUE, "600", "middle")
        d._text(x, 124, sub, 11.5, MUTED, anchor="middle")

    d.node(120, 250, "copilot-studio", "Employee Assistant")
    d.node(120, 520, "copilot-studio", "Finance Assistant")
    a = Box(98, 228, 44, 44)
    b = Box(98, 498, 44, 44)

    d.group(230, 160, 820, 580, "Azure API Management", "plain", "apim")
    d.group(
        300,
        200,
        280,
        110,
        "Directory MCP server",
        "cloud",
        sublabel="used by both agents",
    )
    a_dir = d.chip(440, 280, "directory_get_my_profile", w=210)
    d.group(
        300,
        340,
        280,
        300,
        "Finance MCP server",
        "cloud",
        sublabel="used by the Finance Assistant only",
    )
    b_spend = d.chip(440, 420, "finance_query_spend", w=210)
    b_cost = d.chip(440, 465, "finance_list_cost_centres", w=210)
    b_fc = d.chip(440, 510, "budgeting_get_forecast", w=210)
    b_upd = d.chip(440, 555, "budgeting_update_…", w=210)

    d.group(
        660,
        200,
        380,
        500,
        "Contoso REST APIs",
        "cloud",
        sublabel="finance + budgeting imports",
    )
    op_dir = d.service(
        855, 280, 300, 44, "GET /directory/me", "on the directory server: both agents"
    )
    op_spend = d.service(
        855, 390, 300, 44, "GET /finance/spend", "Finance only; parameters checked"
    )
    op_cost = d.service(
        855, 470, 300, 44, "GET /finance/cost-centres", "Finance only; needs app role"
    )
    op_fc = d.service(
        855, 550, 300, 44, "GET /budgeting/forecasts", "Finance only; Budget Editors"
    )
    op_upd = d.service(
        855, 630, 300, 44, "PUT /budgeting/forecasts", "write; same allow-list"
    )

    d.arrow([a.right, (300, 250)])
    d.arrow([b.right, (300, 520)])
    d.arrow([(142, 510), (200, 510), (200, 275), (300, 275)])
    d.arrow([a_dir.right, (600, 280), op_dir.left])
    d.arrow([b_spend.right, (630, 420), (630, 390), op_spend.left])
    d.arrow([b_cost.right, (645, 465), (645, 470), op_cost.left])
    d.arrow([b_fc.right, (660, 510), (660, 550), op_fc.left])
    d.arrow([b_upd.right, (675, 555), (675, 630), op_upd.left])

    fn = d.node(1150, 450, "function", "")
    d._text(1150, 418, "Backend APIs", 12.5, INK, "600", "middle")
    for op in (op_dir, op_spend, op_cost, op_fc, op_upd):
        d.arrow([op.right, (1080, op.cy), (1080, 450), fn.left])
    graph = d.service(
        1350, 280, 210, 54, "Microsoft Graph", "each user sees their own profile"
    )
    sql = d.node(
        1350,
        430,
        "sql",
        "Azure SQL: finance",
        "Finance Readers for spend;\napp-only for cost centres",
    )
    d.arrow(
        [fn.right, (1200, 450), (1200, 280), graph.left],
        label="as the user (on-behalf-of)",
        at=(1204, 340),
    )
    d.arrow([(1200, 450), (1200, 430), sql.left])
    sql2 = d.node(
        1350, 600, "sql", "Azure SQL: budgeting", "Budget Editors; write audited"
    )
    d.arrow(
        [(1150, 480), (1150, 600), sql2.left],
        color=ORANGE,
        label="second Contoso system",
        at=(1250, 560),
        anchor="middle",
    )
    d._label(1300, 520, "Same gateway;\ndifferent databases", BLUE, "middle")

    d.code(
        230,
        760,
        820,
        220,
        "contoso-gateway: two maps generate the MCP servers and the allow-list; adding a tool is an access grant",
        [
            "server_definitions = {",
            '  directory = { tools = ["directory_get_my_profile"] }',
            '  finance   = { tools = ["finance_list_cost_centres", "finance_query_spend",',
            '    "budgeting_get_forecast", "budgeting_update_cost_centre_forecast"] } }',
            "agent_definitions = {",
            '  employee-assistant = { servers = ["directory"] }',
            '  finance-assistant  = { servers = ["directory", "finance"] } }',
        ],
    )
    for x in (440, 855):
        d.arrow([(x, 760), (x, 720)], color=GREY, dash="3 3")
    d._label(452, 746, "generates", GREY)
    d._label(867, 746, "generates", GREY)
    d.save("agent-tool-access")


def sequence(
    name,
    title,
    subtitle,
    actors,
    steps,
    width=None,
    step_h=64,
    footer=None,
    updated=None,
):
    """A sequence diagram. actors: (icon or None, label, sub). steps: dicts with
    frm, to (actor index), text, and optionally color, dash, note (text under the arrow)."""
    n = len(actors)
    col_w = 330 if n <= 4 else 300
    left = 150
    W = width or left + col_w * (n - 1) + 150
    top = 150
    H = top + 40 + step_h * len(steps) + (90 if footer else 40)
    d = Diagram(W, H, title, subtitle, updated)
    xs = [left + i * col_w for i in range(n)]
    for x, (icon, label, sub) in zip(xs, actors):
        if icon:
            d.node(x, 108, icon, label, sub, size=40)
        else:
            d.service(x, 108, 150, 46, label, sub)
        d.mid.append(
            f'<path d="M {x} {top + 30} L {x} {H - (62 if footer else 30)}" stroke="{GREY}" stroke-width="1.2" '
            f'stroke-dasharray="4 4" fill="none"/>'
        )
    for i, s in enumerate(steps):
        y = top + 50 + i * step_h
        color = s.get("color", BLUE)
        a, b = xs[s["frm"]], xs[s["to"]]
        if a == b:
            # a check the actor makes on itself; drawn leftwards from the right-most column
            sgn = -1 if s["frm"] == n - 1 else 1
            d.mid.append(
                f'<path d="M {a} {y - 10} L {a + sgn * 46} {y - 10} L {a + sgn * 46} {y + 16} L {a + sgn * 4} {y + 16}" '
                f'fill="none" stroke="{color}" stroke-width="2" marker-end="{d._marker(color)}"/>'
            )
            d._label(a + sgn * 56, y + 2, s["text"], INK, "end" if sgn < 0 else "start")
            d.badge(
                a + sgn * 74 if False else (a - 22 if sgn > 0 else a + 22),
                y + 2,
                i + 1,
                color,
            )
            continue
        dx = 4 if b > a else -4
        d.arrow([(a + dx, y), (b - dx, y)], color=color, dash=s.get("dash"))
        d._label((a + b) / 2, y - 8, s["text"], INK, "middle")
        if s.get("note"):
            d._label((a + b) / 2, y + 18, s["note"], MUTED, "middle")
        d.badge(min(a, b) + 22 if True else a, y, i + 1, color)
    if footer:
        d._text(24, H - 24, footer, 12, MUTED)
    d.save(name)


def auth_sign_in():
    sequence(
        "auth-sign-in",
        "Signing in once: the user, the connector and Microsoft Entra ID",
        "Happens when a connection is created; no client secret is involved",
        [
            ("users", "User", "in the browser"),
            ("power-platform", "Agent's connector", "Power Platform"),
            ("managed-identity", "Connector's\nmanaged identity", "holds no secret"),
            ("entra-id", "Microsoft Entra ID", "agent's app registration"),
        ],
        [
            dict(frm=0, to=1, text="Create connection"),
            dict(
                frm=1,
                to=3,
                text="Redirect to sign in as the agent's app, scope Tools.Read",
                note="client_id = agent app, redirect = connector callback",
            ),
            dict(
                frm=0,
                to=3,
                text="Sign in (password, MFA); no consent prompt",
                note="the app is pre-authorised for Tools.Read",
            ),
            dict(
                frm=3,
                to=1,
                text="Authorization code, returned to the callback URL",
                dash="6 3",
                color=PURPLE,
            ),
            dict(frm=1, to=2, text="Ask for a token for the identity"),
            dict(
                frm=2,
                to=1,
                text="Signed assertion (issuer, subject)",
                dash="6 3",
                color=PURPLE,
            ),
            dict(
                frm=1,
                to=3,
                text="Redeem the code, proving who it is with the assertion",
                note="in place of a client secret",
            ),
            dict(
                frm=3,
                to=3,
                text="Check issuer, subject and audience\nagainst the federated credential",
            ),
            dict(
                frm=3,
                to=1,
                text="Access token: aud = API, azp = agent app, scp = Tools.Read, oid = user",
                dash="6 3",
                color=PURPLE,
            ),
        ],
        footer="No federated credential, no token: Entra ID answers AADSTS70025. Tokens are kept on the connection and refreshed.",
    )


def auth_tool_call():
    sequence(
        "auth-tool-call",
        "A tool call at the gateway: what API Management checks",
        "The same policy runs for the MCP server and for the REST API",
        [
            ("copilot-studio", "Agent", "via its connection"),
            ("apim", "API Management", "agent's MCP server + API policy"),
            ("function", "Backend API", "private endpoint"),
        ],
        [
            dict(frm=0, to=1, text="tools/call finance_query_spend (Bearer token)"),
            dict(
                frm=1, to=1, text="Validate token: signature, tenant, audience, scope"
            ),
            dict(
                frm=1,
                to=1,
                text="Is azp this server's agent? Is the tool allowed for azp?",
                color=RED,
            ),
            dict(frm=1, to=1, text="Check the parameters (category, dates, range)"),
            dict(
                frm=1, to=1, text="Rate limit per agent and user; write the audit trace"
            ),
            dict(frm=1, to=2, text="GET /tools/finance/spend?..., token forwarded"),
            dict(
                frm=2,
                to=1,
                text="Result, produced as the user",
                dash="6 3",
                color=PURPLE,
            ),
            dict(frm=1, to=0, text="Tool result", dash="6 3", color=PURPLE),
        ],
        updated=NEW,
        footer="Any failed check stops here: 401 for the token, 403 for the allow-list, 400 for bad parameters, 429 for the limit. Copilot Studio shows each to the agent as tool text.",
    )


def auth_obo():
    sequence(
        "auth-obo",
        "Delegated access: reading Graph and SQL as the user (on-behalf-of)",
        "The API holds no standing access to the user's data",
        [
            ("apim", "API Management", "forwards the user's token"),
            ("function", "Backend API", "confidential client"),
            ("entra-id", "Microsoft Entra ID", ""),
            (None, "Graph or Azure SQL", "applies the user's rights"),
        ],
        [
            dict(frm=0, to=1, text="Request with the user's token (aud = this API)"),
            dict(
                frm=1,
                to=2,
                text="Exchange the user's token for a Graph or SQL token",
                note="proves itself with a managed identity (a client secret is the fallback)",
            ),
            dict(
                frm=2,
                to=2,
                text="Is this API allowed to ask?\nWas admin consent granted?",
            ),
            dict(
                frm=2,
                to=1,
                text="New token for Graph or SQL; still the same user",
                dash="6 3",
                color=PURPLE,
            ),
            dict(frm=1, to=3, text="Call with the new token"),
            dict(
                frm=3,
                to=3,
                text="Authorises the user: directory\nprofile, or a SQL database user",
                color=RED,
            ),
            dict(
                frm=3,
                to=1,
                text="Only what that user may see",
                dash="6 3",
                color=PURPLE,
            ),
        ],
        footer="Someone outside Contoso Finance Readers has no database user, so finance_query_spend is refused, whichever agent they use.",
        updated=NEW,
    )


def access_models():
    d = Diagram(
        1500,
        800,
        "Delegated access and app-only access",
        "The same agent and the same user can reach data in two different ways",
        NEW,
    )
    xs = [190, 560, 930, 1300]
    heads = [
        ("Caller", "The user signs in through the agent"),
        ("Gateway", "Checks the token, the agent and the tool"),
        ("Backend", "Reaches the data"),
        ("Source system", "Decides what comes back"),
    ]
    for x, h, sub in zip(xs, [h[0] for h in heads], [h[1] for h in heads]):
        d._text(x, 104, h, 15, BLUE, "600", "middle")
        d._text(x, 124, sub, 11.5, MUTED, anchor="middle")

    def lane(top, title, sub, cy, rows):
        d.group(24, top, 1452, 300, title, "plain", sublabel=sub)
        agent = d.node(xs[0], cy, "copilot-studio", "Agent", rows["agent"])
        apim = d.node(xs[1], cy, "apim", "API Management", rows["apim"])
        fn = d.node(xs[2], cy, "function", "Backend API", rows["fn"])
        src = d.node(
            xs[3], cy, "sql", rows.get("src_name", "Azure SQL or Graph"), rows["src"]
        )
        d.arrow(
            [agent.right, apim.left],
            label=rows["a1"],
            at=((xs[0] + xs[1]) / 2 + 6, cy - 22),
            anchor="middle",
        )
        d.arrow(
            [apim.right, fn.left],
            label=rows["a2"],
            at=((xs[1] + xs[2]) / 2 + 6, cy - 22),
            anchor="middle",
        )
        d.arrow(
            [fn.right, src.left],
            color=PURPLE,
            label=rows["a3"],
            at=((xs[2] + xs[3]) / 2 + 6, cy - 22),
            anchor="middle",
        )
        for x, text in zip(xs[1:], rows["decides"]):
            d._text(x, cy + 100, text, 12, INK, anchor="middle")
        d._text(44, top + 282, rows["use"], 12, MUTED)

    lane(
        150,
        "Delegated access: acts as the user",
        "The backend passes the user's identity on, so the source applies that user's own permissions",
        262,
        dict(
            agent="user signed in",
            apim="validates the token",
            fn="exchanges the user's token\n(on-behalf-of)",
            src="sees: the user",
            a1="user's token\nscp = Tools.Read",
            a2="the same token",
            a3="a token for the user,\nfrom Microsoft Entra ID",
            decides=[
                "Decides: which agent\nmay use which tool",
                "Proves itself to Entra ID with a\nmanaged identity (a secret is\nthe fallback)",
                "Decides: from the user's\nown permissions",
            ],
            use="Use when people already have access to the data and should never see more than that. Here: the directory profile and spending.",
        ),
    )
    lane(
        470,
        "App-only access: acts as the app",
        "The backend uses its own identity, so the gateway decides who may use the tool",
        582,
        dict(
            agent="user signed in",
            apim="validates the token",
            fn="uses its managed identity\nfor the data",
            src="sees: the app",
            a1="user's token\n(who is asking)",
            a2="the same token",
            a3="the app's own token,\nfrom its managed identity",
            decides=[
                "Decides: which agent, and which\npeople (an app role or group\non the user's token)",
                "Proves itself to Entra ID with a\nmanaged identity: no secret,\nno user token",
                "Decides: from the app's\npermissions, the same for\nevery user",
            ],
            use="Use when people have no direct access to the data and the gateway is the control. Here: the cost centres.",
        ),
    )
    d.save("access-models")


def access_matrix():
    d = Diagram(
        1300,
        720,
        "Access model and credential are separate choices",
        "A managed identity changes how the backend proves who it is, not whose permissions apply",
        NEW,
    )
    cx = [540, 980]
    for x, h, sub in zip(
        cx,
        ["Client secret", "Managed identity"],
        [
            "A password to store and rotate",
            "No secret: trusted through a federated credential",
        ],
    ):
        d._text(x, 112, h, 15, BLUE, "600", "middle")
        d._text(x, 132, sub, 11.5, MUTED, anchor="middle")
    rows = [
        (
            150,
            "Delegated access",
            "The backend acts as\nthe signed-in user",
            "Source system\nsees the user",
        ),
        (
            400,
            "App-only access",
            "The backend acts as\nthe application",
            "Source system\nsees the app",
        ),
    ]
    for y, h, sub, sees in rows:
        d._text(30, y + 34, h, 15, INK, "600")
        d._text(30, y + 56, sub, 12, MUTED)
        d._text(30, y + 100, sees, 12, INK, "600")

    def cell(x, y, label, icon, body, chip, chip_color, chip_w):
        d.group(x, y, 420, 215, label, "plain", icon)
        for i, line in enumerate(body):
            d._text(x + 16, y + 66 + i * 19, line, 12.5, INK)
        d.chip(x + 16 + chip_w / 2, y + 185, chip, chip_w, chip_color)

    cell(
        330,
        150,
        "Delegated, client secret",
        None,
        [
            "On-behalf-of exchange.",
            "The API presents a client secret to",
            "Entra ID with the user's token.",
            "Works, but the secret is a liability.",
        ],
        "built and tested",
        BLUE,
        150,
    )
    cell(
        770,
        150,
        "Delegated, managed identity",
        "managed-identity",
        [
            "The same exchange. The user-assigned",
            "managed identity supplies the client",
            "assertion in place of the secret.",
            "The default here.",
        ],
        "built and tested",
        GREEN,
        150,
    )
    cell(
        330,
        400,
        "App-only, client secret",
        None,
        [
            "Client credentials flow with a secret.",
            "A broad identity and a secret to rotate.",
            "",
            "Avoid: use a managed identity instead.",
        ],
        "avoid",
        RED,
        90,
    )
    cell(
        770,
        400,
        "App-only, managed identity",
        "managed-identity",
        [
            "The managed identity gets its own token",
            "for the source system. No user token.",
            "Needs a database user or app role for",
            "that identity, scoped narrowly.",
        ],
        "for data users cannot reach; built and tested",
        GREEN,
        350,
    )
    d.group(24, 640, 1252, 56, "", "plain")
    d._text(
        44,
        674,
        "Pick the row by asking whose permissions should apply. Pick the column by asking how the backend should prove itself.",
        13,
        INK,
        "600",
    )
    d.save("access-matrix")


def auth_app_only():
    sequence(
        "auth-app-only",
        "App-only access: a tool for data users cannot reach directly",
        "The gateway is the control, because the source cannot tell users apart",
        [
            ("copilot-studio", "Agent", "user signed in"),
            ("apim", "API Management", "agent's MCP server + API policy"),
            ("function", "Backend API", "private endpoint"),
            ("entra-id", "Microsoft Entra ID", ""),
            ("sql", "Azure SQL", "data users cannot read directly"),
        ],
        [
            dict(frm=0, to=1, text="tools/call finance_list_cost_centres"),
            dict(
                frm=1,
                to=1,
                text="Validate the token; is the tool on this agent's allow-list?",
            ),
            dict(
                frm=1,
                to=1,
                text="Does the user's token carry the app role for this tool?",
                color=RED,
            ),
            dict(
                frm=1,
                to=1,
                text="Rate limit; write the audit trace (agent, user, decision)",
            ),
            dict(
                frm=1,
                to=2,
                text="GET /tools/finance/cost-centres, token fwd",
                note="Easy Auth checks it; not used downstream",
            ),
            dict(
                frm=2,
                to=3,
                text="Ask for an Azure SQL token",
                note="as its managed identity; no secret",
            ),
            dict(
                frm=3,
                to=2,
                text="Token: the app's identity, no user",
                dash="6 3",
                color=PURPLE,
            ),
            dict(frm=2, to=4, text="Query cost centres with that token"),
            dict(
                frm=4,
                to=4,
                text="Authorises the app: the database user\ncreated for the managed identity",
                color=RED,
            ),
            dict(
                frm=4,
                to=2,
                text="Rows: the same for every user",
                dash="6 3",
                color=PURPLE,
            ),
            dict(frm=2, to=1, text="Result", dash="6 3", color=PURPLE),
            dict(frm=1, to=0, text="Tool result", dash="6 3", color=PURPLE),
        ],
        footer="Azure SQL never sees the user. The controls are the gateway's check on who may use the tool and the app's narrow database permissions.",
        step_h=58,
        updated=NEW,
    )


def assurance_pillars():
    d = Diagram(
        1400,
        520,
        "Five assurance pillars before an agent proceeds",
        "Gateway tests prove the front door; evals prove the agent",
        NEW,
    )
    d._text(700, 118, "Assurance to proceed", 16, INK, "600", "middle")
    d.mid.append(
        f'<rect x="80" y="132" width="1240" height="8" rx="2" fill="{GREEN}" opacity="0.85"/>'
    )
    pillars = [
        (
            160,
            "Security",
            "Contain blast radius:\nallow-lists, private path,\nno secrets on agents",
        ),
        (
            420,
            "Governance",
            "Who grants tools,\nwho stops an agent,\ndata policy allow-list",
        ),
        (
            680,
            "Observability",
            "Who called what,\nfor whom; denials\nand silent absence",
        ),
        (940, "AI safety", "Injection, silent\nfailure, write HITL;\nprobes 1–9"),
        (1200, "Evals", "Tool choice,\nfaithfulness, honesty;\nEvaluate + scorecard"),
    ]
    for x, title, body in pillars:
        d.group(x - 110, 170, 220, 260, title, "plain")
        d._text(x, 230, body, 12.5, INK, anchor="middle")
        d.chip(x, 390, "required", w=100, color=GREEN)
    d._text(
        700,
        470,
        "All five must be green enough for Contoso's proceed decision — not just security.",
        13,
        MUTED,
        anchor="middle",
    )
    d.save("assurance-pillars")


def silent_failure():
    d = Diagram(
        1400,
        560,
        "Silent failure: confident answer, empty gateway",
        "The user hears knowledge; the audit trail never got a call",
        NEW,
    )
    d.group(80, 150, 380, 320, "What the user sees", "plain", "copilot-studio")
    d.node(270, 260, "copilot-studio", "Finance Assistant", "Preview / Teams")
    d._text(
        270,
        360,
        "Fluent answer about travel\nspend — no error, no\n“Used tool” line",
        13,
        INK,
        anchor="middle",
    )
    d.chip(270, 430, "looks fine", w=120, color=ORANGE)

    d.group(510, 150, 380, 320, "What broke", "plain")
    d._text(
        700,
        230,
        "Connection Reconnect,\nDNS / VNet lag,\nor tool not wired",
        13,
        INK,
        anchor="middle",
    )
    d.arrow([(460, 310), (510, 310)], color=RED, dash="6 3")
    d.arrow([(890, 310), (940, 310)], color=RED, dash="6 3")
    d.refused(700, 300, "MCP call never left\nCopilot Studio", "middle")

    d.group(940, 150, 380, 320, "What the gateway sees", "plain", "apim")
    d.node(1130, 260, "apim", "API Management", "Finance MCP server")
    d._text(
        1130,
        360,
        "No AppTraces row\nNo decision / operation\nfor that conversation",
        13,
        INK,
        anchor="middle",
    )
    d.chip(1130, 430, "empty audit", w=130, color=RED)

    d._text(
        700,
        510,
        "Detect by absence: agent in use + zero tool calls. Alert on Copilot Studio failed MCP requests (see observability).",
        12.5,
        MUTED,
        anchor="middle",
    )
    d.save("silent-failure")


def evals_loop():
    d = Diagram(
        1400,
        620,
        "Agent eval loop: product Evaluate plus Contoso probes",
        "Score quality, then re-run after every material change",
        NEW,
    )
    d.group(60, 160, 320, 280, "Inputs", "plain")
    d._text(220, 220, "Demo questions\n+ edge cases", 13, INK, "600", "middle")
    d._text(220, 300, "Safety probes 1–9\n(ai-safety.md)", 13, INK, "600", "middle")
    d.chip(220, 390, "test set", w=110)

    d.group(440, 160, 520, 280, "Measure", "plain", "copilot-studio")
    d.service(
        700,
        250,
        280,
        70,
        "Copilot Studio Evaluate",
        "General quality / Compare meaning",
    )
    d.service(
        700,
        360,
        280,
        70,
        "Probe scorecard",
        "Pass/fail vs prediction + gateway join",
    )

    d.group(1020, 160, 320, 280, "Act", "plain")
    d._text(
        1180,
        250,
        "Change instructions,\ntools, HITL, or\nconnection wiring",
        13,
        INK,
        anchor="middle",
    )
    d.chip(1180, 360, "then re-run", w=130, color=GREEN)

    d.arrow([(380, 300), (440, 300)], num=1, num_at=(410, 288))
    d.arrow([(960, 300), (1020, 300)], num=2, num_at=(990, 288))
    d.arrow(
        [(1180, 440), (1180, 520), (220, 520), (220, 440)],
        color=ORANGE,
        dash="6 3",
        num=3,
        num_at=(700, 508),
    )
    d._label(
        700,
        540,
        "Regression: every material change re-enters the loop",
        ORANGE,
        "middle",
    )
    d._text(
        700,
        580,
        "A high Evaluate score with zero gateway rows is not a quality win — join to observability.",
        12.5,
        MUTED,
        anchor="middle",
    )
    d.save("evals-loop")


if __name__ == "__main__":
    solution_architecture()
    networking_topology()
    two_front_doors()
    agent_tool_access()
    assurance_pillars()
    silent_failure()
    evals_loop()
    auth_sign_in()
    auth_tool_call()
    auth_obo()
    access_models()
    access_matrix()
    auth_app_only()
