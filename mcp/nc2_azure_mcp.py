# Date : 20260206
# Author : Andrew Nam
# email : nexus2019@naver.com
# Goal : use Claude Desktop to connect nc2_azure_mcp.py server and monitor azure resource group

from __future__ import annotations

import json
import subprocess
from typing import Any, Dict, List

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("nc2-azure-prevalidation")

def _run_az(cmd: List[str]) -> Dict[str, Any]:
    """
    Run an Azure CLI command and return parsed JSON.
    Safety notes:
    - shell=False
    - returns {"error": "..."} on failure
    """
    full_cmd = ["az", *cmd, "-o", "json"]
    p = subprocess.run(full_cmd, capture_output=True, text=True, shell=False)

    if p.returncode != 0:
        err = (p.stderr or p.stdout).strip()
        return {"error": err, "cmd": " ".join(full_cmd)}

    out = p.stdout.strip()
    if not out:
        return {}

    try:
        return json.loads(out)
    except json.JSONDecodeError:
        # sometimes az returns non-json output if not logged in
        return {"error": f"Non-JSON output returned. Output was: {out[:300]}", "cmd": " ".join(full_cmd)}

@mcp.tool()
def azure_account_show() -> Dict[str, Any]:
    """Show current Azure account/subscription context."""
    return _run_az(["account", "show"])

@mcp.tool()
def azure_list_vnets(resource_group: str) -> Dict[str, Any]:
    """List VNets in a resource group."""
    return {"vnets": _run_az(["network", "vnet", "list", "-g", resource_group])}

@mcp.tool()
def azure_list_subnets(resource_group: str, vnet_name: str) -> Dict[str, Any]:
    """List subnets in a VNet (includes delegation info)."""
    return {
        "subnets": _run_az(["network", "vnet", "subnet", "list", "-g", resource_group, "--vnet-name", vnet_name])
    }

@mcp.tool()
def azure_list_nat_gateways(resource_group: str) -> Dict[str, Any]:
    """List NAT Gateways in a resource group."""
    return {"nat_gateways": _run_az(["network", "nat", "gateway", "list", "-g", resource_group])}

def _summarize_subnets(subnets: List[Dict[str, Any]]) -> Dict[str, Any]:
    summary = []
    for s in subnets or []:
        delegations = s.get("delegations") or []
        delegation_names = [d.get("serviceName") for d in delegations if isinstance(d, dict)]
        summary.append(
            {
                "name": s.get("name"),
                "addressPrefix": s.get("addressPrefix"),
                "addressPrefixes": s.get("addressPrefixes"),
                "delegations": delegation_names,
                "privateEndpointNetworkPolicies": s.get("privateEndpointNetworkPolicies"),
                "privateLinkServiceNetworkPolicies": s.get("privateLinkServiceNetworkPolicies"),
            }
        )
    return {"count": len(subnets or []), "items": summary}

@mcp.tool()
def nc2_azure_prevalidation(resource_group: str, vnet_name: str) -> Dict[str, Any]:
    """
    Minimal NC2 Azure pre-validation (starter).
    Returns PASS/FAIL and reasons.

    NOTE: This is not a complete official NC2 checklist.
    It's intentionally minimal so you can confirm MCP + az auth + connectivity works first.
    """
    account = azure_account_show()
    if "error" in account:
        return {
            "status": "FAIL",
            "reasons": ["Azure CLI not authenticated or not returning JSON."],
            "details": account,
        }

    vnets_resp = azure_list_vnets(resource_group)
    subnets_resp = azure_list_subnets(resource_group, vnet_name)
    nat_resp = azure_list_nat_gateways(resource_group)

    # Extract lists safely
    vnets = vnets_resp.get("vnets", [])
    subnets = subnets_resp.get("subnets", [])
    nat_gws = nat_resp.get("nat_gateways", [])

    reasons = []
    checks = {}

    # Check 1: VNet exists
    vnet_names = [v.get("name") for v in vnets if isinstance(v, dict)]
    checks["vnet_exists"] = vnet_name in vnet_names
    if not checks["vnet_exists"]:
        reasons.append(f"VNet '{vnet_name}' not found in resource group '{resource_group}'.")

    # Check 2: at least one subnet
    checks["subnet_count_ok"] = isinstance(subnets, list) and len(subnets) >= 1
    if not checks["subnet_count_ok"]:
        reasons.append(f"No subnets found in VNet '{vnet_name}' (RG '{resource_group}').")

    # Check 3: NAT gateway present (common outbound requirement in many designs)
    checks["nat_gateway_present"] = isinstance(nat_gws, list) and len(nat_gws) >= 1
    if not checks["nat_gateway_present"]:
        reasons.append("No NAT Gateway found in the resource group (outbound design may not meet requirements).")

    status = "PASS" if len(reasons) == 0 else "FAIL"

    return {
        "status": status,
        "checks": checks,
        "reasons": reasons,
        "account": {
            "name": account.get("name"),
            "tenantId": account.get("tenantId"),
            "id": account.get("id"),
            "user": account.get("user"),
        },
        "observations": {
            "vnets_found": vnet_names,
            "subnets": _summarize_subnets(subnets if isinstance(subnets, list) else []),
            "nat_gateway_count": len(nat_gws) if isinstance(nat_gws, list) else 0,
        },
    }

if __name__ == "__main__":
    # Claude Desktop will start this and talk over stdio.
    mcp.run()
