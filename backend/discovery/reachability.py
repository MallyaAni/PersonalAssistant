"""Work out an address for calendar links that a phone can actually open.

The digest's whole value is the "Add" link: the recipient taps it and iOS offers
to add the event. A link to `localhost` defeats that completely and silently —
on the phone, `localhost` is the phone, so the tap fails and nothing explains
why. This is the kind of defect that looks fine in every test run on the machine
that serves it.

So the base address is derived from the host's LAN interface rather than
defaulting to loopback, and a loopback address is reported as unreachable so a
caller can warn instead of sending dead links.
"""

import ipaddress
import socket
from pathlib import Path

# Any address the phone cannot route to. Loopback is the dangerous one because
# it works perfectly on the serving machine.
_UNREACHABLE_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})


# Whether a base URL could be opened from another device on the network.
def is_reachable_from_other_devices(base_url: str) -> bool:
    host = _host_of(base_url)
    if host is None or host in _UNREACHABLE_HOSTS:
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # A hostname that is not an IP literal is assumed routable; resolving it
        # here would be a network call in a pure check.
        return True
    return not (address.is_loopback or address.is_unspecified)


# Whether this process is inside a container, where its own address belongs to a
# private bridge network the phone cannot route to.
def running_in_container() -> bool:
    return Path("/.dockerenv").exists()


# The host's address on its local network, or None when it cannot be determined.
#
# Opening a UDP socket toward a public address sends no packets; it just makes
# the kernel choose the outbound interface, which is the one a phone on the same
# network would reach. Enumerating interfaces directly would need a dependency
# and would still have to guess which one matters.
#
# Inside a container this refuses to answer rather than answering wrongly. The
# address it would find is the container's own bridge address — routable-looking,
# reachable only from the Docker network — and a plausible wrong answer is worse
# than none, because it produces links that fail silently on the phone.
def detect_lan_address() -> str | None:
    if running_in_container():
        return None
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.settimeout(0.5)
        probe.connect(("192.0.2.1", 9))  # TEST-NET-1: reserved, never routed.
        address = probe.getsockname()[0]
    except Exception:
        return None
    finally:
        probe.close()
    if not isinstance(address, str) or address in _UNREACHABLE_HOSTS:
        return None
    return address


# The address to build calendar links from. An explicit setting always wins —
# an operator publishing a real hostname must not be second-guessed — and the
# LAN address is only used to replace a loopback default.
def calendar_base_url(configured: str, port: int = 8000) -> str:
    if is_reachable_from_other_devices(configured):
        return configured
    lan = detect_lan_address()
    if lan is None:
        return configured
    return f"http://{lan}:{port}/api/v1/discovery"


def _host_of(base_url: str) -> str | None:
    without_scheme = base_url.split("://", 1)[-1]
    authority = without_scheme.split("/", 1)[0]
    if not authority:
        return None
    # Strip a port, taking care not to break an IPv6 literal.
    if authority.startswith("["):
        return authority.partition("]")[0].lstrip("[") or None
    return authority.rsplit(":", 1)[0] if ":" in authority else authority
