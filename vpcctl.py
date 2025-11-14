"""
A test script for cli
"""
import subprocess
import click
import json
import logging
import sys
import ipaddress

from utils import (
    get_namespace_by_subnet,
    get_subnet_gateway,
    get_subnet_gateway_by_name,
    get_bridge_cidr,
    get_subnets,
    get_bridge_gateway
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

@click.group()
def vpcctl():
    """
    """
    pass


@click.command()
@click.argument("name", required=True)
@click.argument("cidr", required=True)
def create_vpc(name, cidr):
    """
    Creates a VPC with name and a cidr
    """
    bridge_name = f"br-{name}"
    
    check_result = subprocess.run(
        ["ip", "link", "show", bridge_name],
        capture_output=True,
        text=True
    )
    
    if check_result.returncode == 0:
        logger.warning(f"VPC '{name}' already exists. Skipping creation.")
        return
    
    logger.info(f"Creating VPC '{name}' with CIDR {cidr}")
    
    logger.info(f"Creating bridge interface: {bridge_name}")
    subprocess.run(["ip", "link", "add", "name", bridge_name, "type", "bridge"], check=True)
    
    logger.info(f"Assigning IP address {cidr} to {bridge_name}")
    subprocess.run(["ip", "addr", "add", cidr, "dev", bridge_name], check=True)
    
    logger.info(f"Bringing up bridge interface: {bridge_name}")
    subprocess.run(["ip", "link", "set", bridge_name, "up"], check=True)
    
    logger.info(f"VPC '{name}' created successfully with network {cidr}")
    subprocess.run(["ip", "-4", "addr", "show", "dev", bridge_name], check=True)


@click.command()
@click.argument('vpc', required=True)
@click.argument('name', required=True)
@click.argument('cidr', required=True)
@click.option("--type", type=click.Choice(["public", "private"]), default='private')
def add_subnet(vpc, name, cidr, type):
    """
    Creates a subnet on a vpc within the specified cidr
    A subnet can be either public or private
    """
    check_result = subprocess.run(
        ["ip", "netns", "list"],
        capture_output=True,
        text=True
    )
    
    if name in check_result.stdout:
        logger.warning(f"Subnet '{name}' already exists. Skipping creation.")
        return
    
    bridge_check = subprocess.run(
        ["ip", "link", "show", f"br-{vpc}"],
        capture_output=True,
        text=True
    )
    
    if bridge_check.returncode != 0:
        logger.error(f"VPC '{vpc}' does not exist. Please create the VPC first.")
        return
    
    logger.info(f"Creating {type} subnet '{name}' in VPC '{vpc}' with CIDR {cidr}")
    
    logger.info(f"Creating network namespace: {name}")
    subprocess.run(["ip", "netns", "add", name], check=True)

    sub_ip, sub_range = cidr.split("/")
    
    # Get the VPC bridge gateway (already assigned during VPC creation)
    bridge_gateway = get_bridge_gateway(f"br-{vpc}")
    logger.info(f"Using VPC bridge gateway: {bridge_gateway}")

    logger.info(f"Creating veth pair: veth-{name} <-> veth-{name}-br")
    subprocess.run(["ip", "link", "add", f"veth-{name}", "type", "veth", "peer", "name", f"veth-{name}-br"], check=True)
    
    logger.info(f"Attaching veth-{name} to namespace {name}")
    subprocess.run(["ip", "link", "set", f"veth-{name}", "netns", name], check=True)
    
    logger.info(f"Attaching veth-{name}-br to bridge br-{vpc}")
    subprocess.run(["ip", "link", "set", f"veth-{name}-br", "master", f"br-{vpc}"], check=True)
    
    logger.info("Bringing up interfaces")
    subprocess.run(["ip", "link", "set", f"veth-{name}-br", "up"], check=True)
    subprocess.run(["ip", "link", "set", f"br-{vpc}", "up"], check=True)
    
    # Assign first available IP from the subnet CIDR to the subnet namespace
    next_ip = str(list(ipaddress.ip_network(cidr, strict=False).hosts())[0])
    logger.info(f"Assigning IP {next_ip}/{sub_range} to veth-{name} in namespace {name}")
    subprocess.run(["ip", "netns", "exec", name, "ip", "addr", "add", f"{next_ip}/{sub_range}", "dev", f"veth-{name}"], check=True)
    
    logger.info("Bringing up veth interface in namespace")
    subprocess.run(["ip", "netns", "exec", name, "ip", "link", "set", f"veth-{name}", "up"], check=True)
    subprocess.run(["ip", "netns", "exec", name, "ip", "link", "set", "lo", "up"], check=True)

    logger.info(f"Adding route to bridge gateway {bridge_gateway}")
    subprocess.run(["ip", "netns", "exec", name, "ip", "route", "add", bridge_gateway, "dev", f"veth-{name}"], check=True)

    # Set default route through the VPC bridge gateway
    logger.info(f"Setting default route via {bridge_gateway}")
    subprocess.run(["ip", "netns", "exec", name, "ip", "route", "add", "default", "via", bridge_gateway, "dev", f"veth-{name}"], check=True)
    
    if type == "public":
        logger.info(f"Configuring NAT for public subnet {name}")
        # MASQUERADE only this specific public subnet
        subprocess.run(["iptables", "-t", "nat", "-A", "POSTROUTING", "-s", cidr, "!", "-o", f"br-{vpc}", "-j", "MASQUERADE"], check=True)
        
        # Allow forwarding only for this specific public subnet
        subprocess.run(["iptables", "-A", "FORWARD", "-s", cidr, "-j", "ACCEPT"], check=True)
    
        # Allow return traffic to this public subnet
        subprocess.run(["iptables", "-A", "FORWARD", "-d", cidr, "-m", "state", "--state", "ESTABLISHED,RELATED", "-j", "ACCEPT"], check=True)
        
        logger.info(f"NAT gateway configured for subnet {name}")
    else:
        logger.info(f"Blocking outbound internet access for private subnet {name}")
        # Block private subnet from reaching the internet (anything not in VPC CIDR)
        vpc_cidr = get_bridge_cidr(f"br-{vpc}")
        vpc_network = str(ipaddress.ip_network(vpc_cidr, strict=False))
        
        # Allow internal VPC traffic
        subprocess.run(["iptables", "-A", "FORWARD", "-s", cidr, "-d", vpc_network, "-j", "ACCEPT"], check=True)
        subprocess.run(["iptables", "-A", "FORWARD", "-d", cidr, "-s", vpc_network, "-j", "ACCEPT"], check=True)
        
        # Block everything else from this private subnet going out
        subprocess.run(["iptables", "-A", "FORWARD", "-s", cidr, "!", "-d", vpc_network, "-j", "DROP"], check=True)
        
        logger.info(f"Private subnet {name} blocked from internet access")
    
    logger.info(f"Subnet '{name}' created successfully as {type} subnet")

@click.command()
@click.argument("vpc_a", required=True)
@click.argument("vpc_b", required=True)
def peer_vpcs(vpc_a, vpc_b):
    """
    Peers two vpcs together
    """
    logger.info(f"Peering VPC '{vpc_a}' with VPC '{vpc_b}'")
    
    logger.info("Creating veth pair for VPC peering")
    subprocess.run(["ip", "link", "add", f"veth-{vpc_a}", "type", "veth", "peer", "name", f"veth-{vpc_b}"], check=True)

    logger.info("Attaching veth interfaces to respective bridges")
    subprocess.run(["ip", "link", "set", f"veth-{vpc_a}", "master", f"br-{vpc_a}"], check=True)
    subprocess.run(["ip", "link", "set", f"veth-{vpc_b}", "master", f"br-{vpc_b}"], check=True)

    vpc_a_cidr = str(ipaddress.ip_network(get_bridge_cidr(f"br-{vpc_a}"), strict=False))
    vpc_b_cidr = str(ipaddress.ip_network(get_bridge_cidr(f"br-{vpc_b}"), strict=False))
    logger.info(f"VPC '{vpc_a}' CIDR: {vpc_a_cidr}")
    logger.info(f"VPC '{vpc_b}' CIDR: {vpc_b_cidr}")

    logger.info("Bringing up peering interfaces")
    subprocess.run(["ip", "link", "set", f"veth-{vpc_a}", "up"], check=True)
    subprocess.run(["ip", "link", "set", f"veth-{vpc_b}", "up"], check=True)

    logger.info("Assigning IP addresses for peering")
    subprocess.run(["ip", "addr", "add", "192.168.255.1/30", "dev", f"veth-{vpc_a}"], check=True)
    subprocess.run(["ip", "addr", "add", "192.168.255.2/30", "dev", f"veth-{vpc_b}"], check=True)

    logger.info("Adding static routes between VPCs")
    subprocess.run(["ip", "route", "replace", vpc_b_cidr, "via", "192.168.255.2", "dev", f"veth-{vpc_a}"], check=True)
    subprocess.run(["ip", "route", "replace", vpc_a_cidr, "via", "192.168.255.1", "dev", f"veth-{vpc_b}"], check=True)

    logger.info("Updating iptables rules for peering")
    subprocess.run(["iptables", "-D", "FORWARD", "-s", vpc_a_cidr, "-d", vpc_b_cidr, "-j" , "DROP"], check=False)
    subprocess.run(["iptables", "-D", "FORWARD", "-s", vpc_b_cidr, "-d", vpc_a_cidr, "-j" , "DROP"], check=False)
    subprocess.run(["iptables", "-A", "FORWARD", "-i", f"br-{vpc_a}", "-o", f"br-{vpc_b}", "-j", "ACCEPT"], check=False)
    subprocess.run(["iptables", "-A", "FORWARD", "-i", f"br-{vpc_b}", "-o", f"br-{vpc_a}", "-j", "ACCEPT"], check=False)

    vpc_a_subs = get_subnets(vpc_a, silent=True)
    vpc_b_subs = get_subnets(vpc_b, silent=True)

    vpc_a_gateway_cidr = get_bridge_cidr(f"br-{vpc_a}")
    vpc_b_gateway_cidr = get_bridge_cidr(f"br-{vpc_b}")

    vpc_a_network = str(ipaddress.ip_network(vpc_a_gateway_cidr, strict=False).network_address) + "/" + str(ipaddress.ip_network(vpc_a_gateway_cidr, strict=False).prefixlen)
    vpc_b_network = str(ipaddress.ip_network(vpc_b_gateway_cidr, strict=False).network_address) + "/" + str(ipaddress.ip_network(vpc_b_gateway_cidr, strict=False).prefixlen)

    logger.info(f"Adding routes in VPC '{vpc_a}' subnets to reach VPC '{vpc_b}'")
    for sub in vpc_a_subs:
        sub_gateway = str(get_subnet_gateway_by_name(sub))
        logger.info(f"Adding route in subnet '{sub}' via gateway {sub_gateway}")
        subprocess.run(["ip", "netns", "exec", sub, "ip", "route", "add", vpc_b_network, "via", sub_gateway, "dev", f"veth-{sub}"], check=True)

    logger.info(f"Adding routes in VPC '{vpc_b}' subnets to reach VPC '{vpc_a}'")
    for sub in vpc_b_subs:
        sub_gateway = str(get_subnet_gateway_by_name(sub))
        logger.info(f"Adding route in subnet '{sub}' via gateway {sub_gateway}")
        subprocess.run(["ip", "netns", "exec", sub, "ip", "route", "add", vpc_a_network, "via", sub_gateway, "dev", f"veth-{sub}"], check=True)
    
    logger.info(f"VPC peering between '{vpc_a}' and '{vpc_b}' completed successfully")

@click.command()
@click.argument("name", required=True)
@click.argument("port", default=8080)
def deploy_workloads(name, port):
    """
    Deploys a simple python server on a specific subnet
    """
    logger.info(f"Deploying workload in subnet '{name}' on port {port}")
    
    result = subprocess.run(
        ["ip", "netns", "exec", name, "ip", "-4", "addr", "show"],
        capture_output=True,
        text=True,
        check=True
    )
    subnet_ip = None
    for line in result.stdout.splitlines():
        if "inet " in line and " lo" not in line:
            subnet_ip = line.split()[1].split("/")[0]
            break

    if not subnet_ip:
        logger.error(f"No valid IP found for namespace {name}")
        raise RuntimeError(f"No valid IP found for namespace {name}")

    logger.info(f"Starting HTTP server in '{name}' on {subnet_ip}:{port}")
    subprocess.run(
        ["ip", "netns", "exec", name, "python3", "-m", "http.server", str(port), "--bind", subnet_ip],
        check=True
    )

@click.command()
@click.argument("filename", required=True)
def apply_firewall(filename):
    """
    Add Security Groups to a namespaces
    """
    logger.info(f"Applying firewall rules from {filename}")

    with open(filename, "r", encoding="utf-8") as f:
        policies = json.load(f)

    namespace = ""
    policies = policies if isinstance(policies, list) else [policies]
    
    for policy in policies:
        subnet_cidr = policy.get("subnet")
        namespace = get_namespace_by_subnet(subnet_cidr)
        
        if not namespace:
            logger.error(f"No namespace found for subnet {subnet_cidr}")
            continue
        
        logger.info(f"Applying rules to subnet '{namespace}' ({subnet_cidr})")
        logger.info("Flushing existing iptables rules")
        subprocess.run(["ip", "netns", "exec", namespace, "iptables", "-F"], check=True)

        for rule in policy.get("ingress", []):
            port = str(rule["port"])
            protocol = rule["protocol"]
            action = "ACCEPT" if rule["action"] == "allow" else "DROP"
            logger.info(f"Adding rule: {action} {protocol} traffic on port {port}")
            subprocess.run([
                "ip", "netns", "exec", namespace,
                "iptables", "-A", "INPUT",
                "-p", protocol,
                "--dport", port,
                "-j", action
            ], check=True)

    logger.info("Configuring default firewall policies")
    subprocess.run(["ip", "netns", "exec", namespace, "iptables", "-A", "INPUT", "-m", "state", "--state", "ESTABLISHED,RELATED", "-j", "ACCEPT"], check=True)
    subprocess.run(["ip", "netns", "exec", namespace, "iptables", "-A", "INPUT", "-i", "lo", "-j", "ACCEPT"], check=True)
    subprocess.run(["ip", "netns", "exec", namespace, "iptables", "-P", "INPUT", "DROP"], check=True)
    logger.info("Firewall rules applied successfully")

@click.command()
@click.argument("name", required=True)
def delete_vpc(name):
    """
    Deletes an existing VPC and all its resources
    """
    bridge_name = f"br-{name}"
    
    check_result = subprocess.run(
        ["ip", "link", "show", bridge_name],
        capture_output=True,
        text=True
    )
    
    if check_result.returncode != 0:
        logger.warning(f"VPC '{name}' does not exist. Nothing to delete.")
        return
    
    logger.info(f"Deleting VPC '{name}' and all associated resources")
    
    logger.info("Retrieving subnets attached to VPC")
    subnets = get_subnets(name, silent=True)
    
    for subnet in subnets:
        logger.info(f"Deleting subnet '{subnet}'")
        
        logger.info(f"Removing veth pair for subnet '{subnet}'")
        subprocess.run(["ip", "link", "del", f"veth-{subnet}-br"], check=False)
        
        logger.info(f"Deleting network namespace '{subnet}'")
        subprocess.run(["ip", "netns", "del", subnet], check=False)
    
    logger.info("Cleaning up iptables rules")
    try:
        vpc_cidr = get_bridge_cidr(bridge_name)
        subnet_network = str(ipaddress.ip_network(vpc_cidr, strict=False))
        
        subprocess.run(["iptables", "-t", "nat", "-D", "POSTROUTING", "-s", subnet_network, "!", "-o", bridge_name, "-j", "MASQUERADE"], check=False)
        subprocess.run(["iptables", "-D", "FORWARD", "-i", bridge_name, "-j", "ACCEPT"], check=False)
        subprocess.run(["iptables", "-D", "FORWARD", "-o", bridge_name, "-j", "ACCEPT"], check=False)
    except Exception as e:
        logger.warning(f"Could not clean up iptables rules: {e}")
    
    logger.info("Removing peering veth interfaces")
    subprocess.run(["ip", "link", "del", f"veth-{name}"], check=False)
    
    logger.info(f"Deleting bridge interface '{bridge_name}'")
    subprocess.run(["ip", "link", "del", bridge_name], check=True)
    
    logger.info(f"VPC '{name}' and all resources deleted successfully")


@click.command()
def list_vpcs():
    """
    Lists all existing VPCs
    """
    logger.info("Listing all VPCs")
    result = subprocess.run(
        ["ip", "link", "show", "type", "bridge"],
        capture_output=True,
        text=True,
        check=True
    )
    
    vpcs = []
    for line in result.stdout.splitlines():
        if "br-" in line:
            vpc_name = line.split("br-")[1].split(":")[0]
            vpcs.append(vpc_name)
    
    if not vpcs:
        logger.info("No VPCs found")
        return
    
    for vpc in vpcs:
        try:
            cidr = get_bridge_cidr(f"br-{vpc}")
            logger.info(f"VPC: {vpc}, CIDR: {cidr}")
            subnets = get_subnets(vpc, silent=True)
            if subnets:
                logger.info(f"  Subnets: {', '.join(subnets)}")
        except Exception as e:
            logger.error(f"Error retrieving details for VPC {vpc}: {e}")

@click.command()
@click.argument("name", required=True)
def show_vpc(name):
    """
    Shows detailed information about a specific VPC
    """
    bridge_name = f"br-{name}"
    
    check_result = subprocess.run(
        ["ip", "link", "show", bridge_name],
        capture_output=True,
        text=True
    )
    
    if check_result.returncode != 0:
        logger.error(f"VPC '{name}' does not exist")
        return
    
    logger.info(f"VPC Details: {name}")
    
    try:
        cidr = get_bridge_cidr(bridge_name)
        logger.info(f"CIDR: {cidr}")
    except Exception as e:
        logger.error(f"Could not retrieve CIDR: {e}")
    
    logger.info("\nSubnets:")
    get_subnets(name, silent=False)
    
    logger.info("\nBridge Interface Details:")
    subprocess.run(["ip", "addr", "show", bridge_name], check=True)

if __name__ == "__main__":
    vpcctl.add_command(create_vpc)
    vpcctl.add_command(add_subnet)
    vpcctl.add_command(delete_vpc)
    vpcctl.add_command(peer_vpcs)
    vpcctl.add_command(deploy_workloads)
    vpcctl.add_command(apply_firewall)
    vpcctl.add_command(list_vpcs)
    vpcctl.add_command(show_vpc)
    vpcctl()
