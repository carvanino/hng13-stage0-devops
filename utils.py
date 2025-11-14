"""
Utility functions for vpcctl
"""
import subprocess
import ipaddress
import click


def get_namespace_by_subnet(cidr):
    """
    Get the name of a subnet from the provided CIDR
    """
    target_net = ipaddress.ip_network(cidr, strict=False)
    
    result = subprocess.run(["ip", "netns", "list"], capture_output=True, text=True, check=True)
    namespaces = [line.split()[0] for line in result.stdout.splitlines()]

    for ns in namespaces:
        ns_result = subprocess.run(
            ["ip", "netns", "exec", ns, "ip", "-4", "addr", "show"],
            capture_output=True, text=True, check=True
        )
        for line in ns_result.stdout.splitlines():
            line = line.strip()
            if line.startswith("inet "):
                ip_cidr = line.split()[1]
                net = ipaddress.ip_network(ip_cidr, strict=False)
                if net == target_net:
                    return ns
    return ''


def get_subnet_gateway(cidr):
    """
    Returns the next availabe IP in the CIDR range
    """
    net = ipaddress.ip_network(cidr, strict=False)
    return str(next(net.hosts())) # type: ignore


def get_subnet_gateway_by_name(subnet_name):
    """
    Get the gateway IP for a subnet by its namespace name
    """
    result = subprocess.run(
        ["ip", "netns", "exec", subnet_name, "ip", "-4", "addr", "show"],
        capture_output=True,
        text=True,
        check=True
    )
    for line in result.stdout.splitlines():
        line = line.strip()
        if line.startswith("inet") and " lo" not in line:
            ip_cidr = line.split()[1]
            net = ipaddress.ip_network(ip_cidr, strict=False)
            return str(list(net.hosts())[0])
    raise ValueError(f"No valid veth IP found for subnet {subnet_name}")


def get_bridge_cidr(bridge_name):
    """
    Get the cidr of a specified bridge name
    """
    output = subprocess.check_output(
        ["ip", "-4", "addr", "show", "dev", bridge_name],
        text=True
    )
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("inet "):
            return line.split()[1]
    raise RuntimeError(f"No IPv4 address found for {bridge_name}")


def get_subnets(vpc, silent=False):
    """
    Lists all subnets attached to a VPC
    """
    result = subprocess.run(
        ["ip", "link", "show", "master", f"br-{vpc}"],
        capture_output=True,
        text=True,
        check=False,
    )
    
    if result.returncode != 0:
        return []

    subnets = []
    
    for line in result.stdout.splitlines():
        if "veth-" in line and "-br@" in line:
            subnet_name = line.split("veth-")[1].split("-br")[0]
            subnets.append(subnet_name)
            
            ip_result = subprocess.run(
                ["ip", "netns", "exec", subnet_name, "ip", "-4", "addr", "show"], 
                capture_output=True, 
                text=True,
                check=False
            )
            
            if ip_result.returncode == 0 and not silent:
                for ip_line in ip_result.stdout.splitlines():
                    if "inet " in ip_line:
                        ip = ip_line.split()[1]
                        click.echo(f"Subnet: {subnet_name}, IP: {ip}")
    return subnets


def get_bridge_gateway(bridge_name):
    """
    Gets the IP address of a bridge (VPC)
    """
    output = subprocess.check_output(
        ["ip", "-4", "addr", "show", "dev", bridge_name],
        text=True
    )
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("inet "):
            return line.split()[1].split('/')[0]
    raise RuntimeError(f"No IPv4 address found for {bridge_name}")
