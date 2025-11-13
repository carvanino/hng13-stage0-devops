"""
A test script for cli
"""
import subprocess
import click
import json


import ipaddress

def get_namespace_by_subnet(cidr):
    """
    Get the name of a subnet from the provided CIDR
    """
    target_net = ipaddress.ip_network(cidr, strict=False)
    
    # List all namespaces
    result = subprocess.run(["ip", "netns", "list"], capture_output=True, text=True, check=True)
    namespaces = [line.split()[0] for line in result.stdout.splitlines()]

    for ns in namespaces:
        # Get IPs in the namespace
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
    # list(net.hosts()) returns all usable IPs
    return str(next(net.hosts())) # type: ignore

def get_subnet_gateway_by_name(subnet_name):
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
            return str(list(net.hosts())[0])  # first usable IP
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

def get_subnets(vpc):
    """
    Lists all subnets attached to a VPC
    """
    result = subprocess.run(
        ["ip", "link", "show", "master", f"br-{vpc}"],
        capture_output=True,
        text=True,
        check=True,
    )

    subnets = []
    
    for line in result.stdout.splitlines():
        if "veth-" in line and "-br@" in line:
            # Extract subnet name from veth-snt-X-br
            subnet_name = line.split("veth-")[1].split("-br")[0]

            subnets.append(subnet_name)
            
            # Get IP from namespace
            ip_result = subprocess.run(
                ["ip", "netns", "exec", subnet_name, "ip", "-4", "addr", "show"], 
                capture_output=True, 
                text=True,
                check=True
            )
            
            for ip_line in ip_result.stdout.splitlines():
                if "inet " in ip_line:
                    ip = ip_line.split()[1]
                    click.echo(f"Subnet: {subnet_name}, IP: {ip}")
    return subnets

@click.group()
def vpcctl():
    """
    """
    pass


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
            # Example: 'inet 10.0.0.1/24 brd 10.0.0.255 scope global br0'
            return line.split()[1].split('/')[0]  # '10.0.0.1'
    raise RuntimeError(f"No IPv4 address found for {bridge_name}")


@click.command()
@click.argument("name", required=True)
@click.argument("cidr", required=True)
def create_vpc(name, cidr):
    """
    Creates a VPC with name and a cidr
    """

    # Creates a bridge with name specified
    subprocess.run(["ip", "link", "add", "name", f"br-{name}", "type", "bridge",], check=True)
    # Add IP address to the created bridge interface 
    subprocess.run(["ip", "addr", "add", f"{cidr}", "dev", f"br-{name}"], check=True)
    # Brings the created bridge up
    subprocess.run(["ip", "link", "set", f"br-{name}", "up"], check=True)

    click.echo(f"You have successfully created the VPC {name} within the network {cidr} as specified")
    subprocess.run(["ip", "-4", "addr", "show", "dev", f"br-{name}"], check=True)

    # subprocess.run(["bridge", "link", "show"], check=True)


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
    subprocess.run(["ip", "netns", "add", f"{name}"], check=True)

    sub_ip, sub_range = cidr.split("/")
    sub_gateway = get_subnet_gateway(cidr)
    print(f"The subnet gateway is {sub_gateway} and the range is {sub_range}")

    # After creating the namespace (subnet) we must attach it to a eth first
    # ip link add veth-ns1 type veth peer name veth-ns1-br
    subprocess.run(["ip", "link", "add", f"veth-{name}", "type", "veth", "peer", "name", f"veth-{name}-br"], check=True)
    # attach the veth to the namespace (subnet)
    # ip link set veth-dev netns dev
    subprocess.run(["ip", "link", "set", f"veth-{name}", "netns", f"{name}"], check=True)
    # attach the veth to the bridge (vpc)
    subprocess.run(["ip", "link", "set", f"veth-{name}-br", "master", f"br-{vpc}"], check=True)
    # bring up eth and bridge
    subprocess.run(["ip", "link", "set", f"veth-{name}-br", "up"], check=True)
    subprocess.run(["ip", "link", "set", f"br-{vpc}", "up"], check=True)
    # Assign an IP address
    # ip netns exec ns1 ip addr add 10.0.0.2/24 dev veth-ns1
    # subprocess.run(["ip", "netns", "exec", f"{name}", "ip", "addr", "add", cidr, "dev", f"veth-{name}"], check=True)
    subprocess.run(["ip", "addr", "add", f"{sub_gateway}/{sub_range}", "dev", f"br-{vpc}"], check=True)
    next_ip = str(list(ipaddress.ip_network(cidr, strict=False).hosts())[1])
    subprocess.run(["ip", "netns", "exec", f"{name}", "ip", "addr", "add", f"{next_ip}/{sub_range}", "dev", f"veth-{name}"], check=True)
    # Bring up the veth
    subprocess.run(["ip", "netns", "exec", f"{name}", "ip", "link", "set", f"veth-{name}", "up"], check=True)

    subprocess.run(["ip", "netns", "exec", name, "ip", "link", "set", "lo", "up"], check=True)

    # Only set default route

    if type == "public":
        # Set up NAT
        subprocess.run(["ip", "netns", "exec", f"{name}", "ip", "route", "add", "default", "via", sub_gateway], check=True)
        subprocess.run(["iptables", "-t", "nat", "-A", "POSTROUTING", "-s", cidr, "!", "-o", f"br-{vpc}", "-j", "MASQUERADE"], check=True)

        # update iptable rules to allow both incoming and outgoing traffic
        subprocess.run(["iptables", "-A", "FORWARD", "-i", f"br-{vpc}", "-j", "ACCEPT"], check=True)
        subprocess.run(["iptables", "-A", "FORWARD", "-o", f"br-{vpc}", "-j", "ACCEPT"], check=True)

@click.command()
@click.argument("vpc_a", required=True)
@click.argument("vpc_b", required=True)
def peer_vpcs(vpc_a, vpc_b):
    """
    Peers two vpcs together
    """
    # confirm that vpc entered exist

    # Create the veth pair for pairing
    print("Creating the VPC peers veth")
    subprocess.run(["ip", "link", "add", f"veth-{vpc_a}", "type", "veth", "peer", "name", f"veth-{vpc_b}"], check=True)

    # attach veth to interface(vpc)
    print("Attaching the veth to the interface")
    subprocess.run(["ip", "link", "set", f"veth-{vpc_a}", "master", f"br-{vpc_a}"], check=True)
    subprocess.run(["ip", "link", "set", f"veth-{vpc_b}", "master", f"br-{vpc_b}"], check=True)

    # bring up the veths and then the vpcs
    vpc_a_cidr = str(ipaddress.ip_network(get_bridge_cidr(f"br-{vpc_a}"), strict=False))
    print(f"VPC A CIDR is {vpc_a_cidr}")
    vpc_b_cidr = str(ipaddress.ip_network(get_bridge_cidr(f"br-{vpc_b}"), strict=False))
    print(f"VPC B CIDR is {vpc_b_cidr}")

    subprocess.run(["ip", "link", "set", f"veth-{vpc_a}", "up"], check=True)
    subprocess.run(["ip", "link", "set", f"veth-{vpc_b}", "up"], check=True)

    # Add an IP address for peering use
    print("Adding Ip address for peering....")
    subprocess.run(["ip", "addr", "add", "192.168.255.1/30", "dev", f"veth-{vpc_a}"], check=True)
    subprocess.run(["ip", "addr", "add", "192.168.255.2/30", "dev", f"veth-{vpc_b}"], check=True)


    # Add static routes - paths to whicg traffic flows from the host to get to vpc-1
    print("Adding static routes")
    subprocess.run(["ip", "route", "replace", f"{vpc_b_cidr}", "via", "192.168.255.2", "dev", f"veth-{vpc_a}"], check=True)
    subprocess.run(["ip", "route", "replace", f"{vpc_a_cidr}", "via", "192.168.255.1", "dev", f"veth-{vpc_b}"], check=True)

    # Remove isolation rules
    # sudo iptables -D FORWARD -s 10.0.0.0/16 -d 172.16.0.0/16 -j DROP 2>/dev/null || true
    print("Removing and updating IPtables rules to allow forwarding correctly")
    subprocess.run(["iptables", "-D", "FORWARD", "-s", vpc_a_cidr, "-d", vpc_b_cidr, "-j" , "DROP"], check=False)
    subprocess.run(["iptables", "-D", "FORWARD", "-s", vpc_b_cidr, "-d", vpc_a_cidr, "-j" , "DROP"], check=False)
    subprocess.run(["iptables", "-A", "FORWARD", "-i", f"br-{vpc_a}", "-o", f"br-{vpc_b}", "-j", "ACCEPT"], check=False)
    subprocess.run(["iptables", "-A", "FORWARD", "-i", f"br-{vpc_b}", "-o", f"br-{vpc_a}", "-j", "ACCEPT"], check=False)

    # Add routes in subnets to reach the peer VPCs
    vpc_a_subs = get_subnets(vpc_a)
    vpc_b_subs = get_subnets(vpc_b)

    vpc_a_gateway_cidr = get_bridge_cidr(f"br-{vpc_a}")
    vpc_b_gateway_cidr = get_bridge_cidr(f"br-{vpc_b}")

    print("VPC A GATEWAY CIDR -> ", vpc_a_gateway_cidr)
    print("VPC B GATEWAY CIDR -> ", vpc_b_gateway_cidr)

    vpc_a_network = str(ipaddress.ip_network(vpc_a_gateway_cidr, strict=False).network_address) + "/" + str(ipaddress.ip_network(vpc_a_gateway_cidr, strict=False).prefixlen)
    vpc_b_network = str(ipaddress.ip_network(vpc_b_gateway_cidr, strict=False).network_address) + "/" + str(ipaddress.ip_network(vpc_b_gateway_cidr, strict=False).prefixlen)

    print("VPC A GATEWAY CIDR -> ", vpc_a_network)
    print("VPC B GATEWAY CIDR -> ", vpc_b_network)


    print("Appying cidr to the proper gateway")

    print("VPC A SUBS", vpc_a_subs)

    for sub in vpc_a_subs:
        sub_gateway = str(get_subnet_gateway_by_name(sub))
        print(f"SUBNET {sub} gateway is {sub_gateway}")
        subprocess.run(["ip", "netns", "exec", sub, "ip", "route", "add", vpc_b_network, "via", sub_gateway, "dev", f"veth-{sub}"], check=True)

    print("VPC B SUBS", vpc_b_subs)

    for sub in vpc_b_subs:
        sub_gateway = str(get_subnet_gateway_by_name(sub))
        print(f"SUBNET {sub} gateway is {sub_gateway}")
        subprocess.run(["ip", "netns", "exec", sub, "ip", "route", "add", vpc_a_network, "via", sub_gateway, "dev", f"veth-{sub}"], check=True)

@click.command()
@click.argument("name", required=True)
@click.argument("port", default=8080)
def deploy_workloads(name, port):
    """
    Deploys a simple python server on a specific subnet
    """
    result = subprocess.run(
        ["ip", "netns", "exec", name, "ip", "-4", "addr", "show"],
        capture_output=True,
        text=True,
        check=True
    )
    subnet_ip = None
    for line in result.stdout.splitlines():
        if "inet " in line and not line.strip().startswith("127."):
            subnet_ip = line.split()[1].split("/")[0]
            break

    if not subnet_ip:
        raise RuntimeError(f"No valid IP found for namespace {name}")

    print(f"Starting server in {name} on {subnet_ip}:{port}")
    subprocess.run(
        ["ip", "netns", "exec", name, "python3", "-m", "http.server", "8080", "--bind", subnet_ip],
        check=True
    )

@click.command()
@click.argument("filename", required=True)
def apply_firewall(filename):
    """
    Add Security Groups to a namespaces
    """

    with open(filename, "r", encoding="utf-8") as f:
        policies = json.load(f)

    namespace = ""
    
    for policy in policies:
        subnet_cidr = policy["subnet"]
        namespace = get_namespace_by_subnet(subnet_cidr)

        for rule in policy.get("ingress", []):
            port = str(rule["port"])
            protocol = rule["protocol"]
            action = "ACCEPT" if rule["action"] == "allow" else "DROP"
            subprocess.run([
                "ip", "netns", "exec", namespace,
                "iptables", "-A", "INPUT",
                "-p", protocol,
                "--dport", port,
                "-j", action
            ], check=True)

    # Allow established connections
    subprocess.run(["ip", "netns", "exec", namespace, "iptables", "-A", "INPUT", "-m", "state", "ESTABISHED,RELATED", "-j", "ACCEPT"], check=True)
    # Allow loopback
    subprocess.run(["ip", "netns", "exec", namespace, "iptables", "-A", "INPUT", "-i", "lo", "-j", "ACCEPT"], check=True)
    # Set default policy to DROP
    subprocess.run(["ip", "netns", "exec", namespace, "iptables", "-P", "INPUT", "DROP"], check=True)

@click.command()
@click.argument("name", required=True)
def delete_vpc(name):
    """
    Deletes an existing VPC
    """
    subprocess.run(["ip", "link", "del", f"br-{name}"], check=True)
    # Display to user to confirm that the bridge has been deleted
    subprocess.run(["ip", "-4", "addr", "show", "type", "bridge"], check=True)


if __name__ == "__main__":
    vpcctl.add_command(create_vpc)
    vpcctl.add_command(add_subnet)
    vpcctl.add_command(delete_vpc)
    vpcctl.add_command(peer_vpcs)
    vpcctl.add_command(deploy_workloads)
    vpcctl()