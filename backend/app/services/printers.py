import ipaddress
import socket


class PrinterError(Exception):
    """A printer address that is not allowed, or a printer that could not be reached; the message is safe to show."""


def private_addresses(host: str, port: int) -> list[str]:
    """The addresses a host resolves to, all of which must be on a private network: no loopback, link-local or public ones."""
    try:
        found = {info[4][0] for info in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
    except socket.gaierror:
        raise PrinterError("That printer address cannot be found on the network") from None
    for text in found:
        address = ipaddress.ip_address(text.split("%")[0])
        if address.is_loopback or address.is_link_local or address.is_multicast or address.is_unspecified or not address.is_private:
            raise PrinterError("A label printer must be on your private network (for example 192.168.x.x or 10.x.x.x)")
    return sorted(found)


def send_zpl(host: str, port: int, zpl: str, timeout: float = 5.0) -> None:
    """Sends ZPL to a printer's raw port, connecting to the address that was just checked."""
    address = private_addresses(host, port)[0]
    try:
        with socket.create_connection((address, port), timeout=timeout) as connection:
            connection.sendall(zpl.encode("utf-8"))
    except OSError:
        raise PrinterError("Could not reach the label printer. Check that it is on and on the same network as the server") from None
