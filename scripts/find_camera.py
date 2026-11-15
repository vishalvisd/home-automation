#!/usr/bin/env python3
"""
Find an IP camera on the LAN and work out its RTSP URL.

Standard library only. Run on the Mac with:

    python3 -I find_camera.py discover          # ONVIF multicast + ping sweep
    python3 -I find_camera.py onvif IP [user] [password]
                                                # ask the camera for its RTSP URLs
    python3 -I find_camera.py guess IP [user] [password]
                                                # try common RTSP paths with ffprobe

"discover" prints every device that answers an ONVIF WS-Discovery probe,
then pings the whole /24 and prints the ARP table so a camera that does
not speak ONVIF still shows up by its MAC address.
"""

import base64
import hashlib
import os
import socket
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

MULTICAST_GROUP = "239.255.255.250"
WS_DISCOVERY_PORT = 3702

PROBE = """<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
            xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
            xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
            xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
  <e:Header>
    <w:MessageID>uuid:{message_id}</w:MessageID>
    <w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
    <w:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>
  </e:Header>
  <e:Body>
    <d:Probe>
      <d:Types>dn:NetworkVideoTransmitter</d:Types>
    </d:Probe>
  </e:Body>
</e:Envelope>"""

# Paths seen on cheap OEM cameras (XMEye/iCSee, Hisilicon, V380, Hikvision
# and Dahua clones). Order roughly by how common they are.
COMMON_PATHS = [
    "/",
    "/1",
    "/11",
    "/12",
    "/stream1",
    "/stream2",
    "/live",
    "/live/ch00_0",
    "/live/ch00_1",
    "/live/ch0",
    "/live/ch1",
    "/h264",
    "/h264_stream",
    "/h264/ch1/main/av_stream",
    "/h264/ch1/sub/av_stream",
    "/Streaming/Channels/101",
    "/Streaming/Channels/102",
    "/Streaming/Channels/1",
    "/cam/realmonitor?channel=1&subtype=0",
    "/cam/realmonitor?channel=1&subtype=1",
    "/onvif1",
    "/onvif2",
    "/ch0_0.264",
    "/ch0_1.264",
    "/user={user}&password={password}&channel=1&stream=0.sdp?real_stream",
    "/user={user}&password={password}&channel=1&stream=1.sdp?real_stream",
    "/video1",
    "/video2",
    "/media/video1",
    "/media/video2",
    "/mpeg4",
    "/MediaInput/h264",
    "/profile1",
    "/profile2",
    "/av0_0",
    "/av0_1",
]


def local_ip() -> str:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        return probe.getsockname()[0]
    finally:
        probe.close()


def text(element, path, namespaces):
    found = element.find(path, namespaces)
    return found.text.strip() if found is not None and found.text else ""


def ws_discovery(seconds: float = 4.0) -> list[dict]:
    """Send one ONVIF probe and collect every answer."""

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.bind((local_ip(), 0))
    sock.settimeout(seconds)

    message = PROBE.format(message_id=uuid.uuid4()).encode()
    sock.sendto(message, (MULTICAST_GROUP, WS_DISCOVERY_PORT))

    found = {}
    namespaces = {
        "e": "http://www.w3.org/2003/05/soap-envelope",
        "d": "http://schemas.xmlsoap.org/ws/2005/04/discovery",
    }

    while True:
        try:
            data, (address, _port) = sock.recvfrom(65535)
        except socket.timeout:
            break

        try:
            root = ET.fromstring(data)
        except ET.ParseError:
            found.setdefault(address, {"ip": address, "xaddrs": "", "scopes": "(unparseable reply)"})
            continue

        for match in root.iter("{http://schemas.xmlsoap.org/ws/2005/04/discovery}ProbeMatch"):
            found[address] = {
                "ip": address,
                "xaddrs": text(match, "d:XAddrs", namespaces),
                "scopes": text(match, "d:Scopes", namespaces),
            }

    sock.close()
    return list(found.values())


def ping_sweep(my_ip: str) -> None:
    """Ping every host in the /24 once so the ARP table fills up."""

    prefix = my_ip.rsplit(".", 1)[0]
    processes = []

    for host in range(1, 255):
        target = f"{prefix}.{host}"
        processes.append(
            subprocess.Popen(
                ["ping", "-c", "1", "-W", "300", target],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        )

    for process in processes:
        process.wait()


def arp_table() -> list[tuple[str, str]]:
    output = subprocess.run(["arp", "-an"], capture_output=True, text=True).stdout
    rows = []

    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 4 or "incomplete" in line:
            continue
        ip = parts[1].strip("()")
        mac = parts[3]
        if ip.endswith(".255") or mac.startswith("1:0:5e") or mac == "ff:ff:ff:ff:ff:ff":
            continue
        rows.append((ip, mac))

    return sorted(rows, key=lambda row: [int(part) for part in row[0].split(".")])


def command_discover() -> None:
    my_ip = local_ip()
    print(f"This Mac is {my_ip}\n")

    print("ONVIF devices answering WS-Discovery (4 s wait)...")
    devices = ws_discovery()

    if not devices:
        print("  none\n")
    else:
        for device in devices:
            print(f"  {device['ip']}")
            print(f"     service: {device['xaddrs']}")
            print(f"     scopes:  {device['scopes']}")
        print()

    print("Pinging the whole /24 to fill the ARP table (about 1 s)...")
    ping_sweep(my_ip)

    print("\nDevices in the ARP table:")
    for ip, mac in arp_table():
        marker = "  <- this Mac" if ip == my_ip else ""
        print(f"  {ip:15}  {mac}{marker}")

    print(
        "\nA brand-new camera is the IP/MAC you have not seen before. "
        "If nothing new shows up, the camera is probably on a different "
        "subnet (many ship with a fixed address such as 192.168.1.10, "
        "192.168.1.168, 192.168.0.123 or 192.168.1.108)."
    )


def onvif_security_header(user: str, password: str) -> str:
    """WS-UsernameToken with password digest, as ONVIF requires."""

    nonce = os.urandom(16)
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    digest = base64.b64encode(
        hashlib.sha1(nonce + created.encode() + password.encode()).digest()
    ).decode()

    return f"""<s:Header>
  <Security s:mustUnderstand="1"
     xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd">
    <UsernameToken>
      <Username>{user}</Username>
      <Password Type="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-username-token-profile-1.0#PasswordDigest">{digest}</Password>
      <Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-soap-message-security-1.0#Base64Binary">{base64.b64encode(nonce).decode()}</Nonce>
      <Created xmlns="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">{created}</Created>
    </UsernameToken>
  </Security>
</s:Header>"""


def soap(url: str, body: str, user: str, password: str) -> ET.Element:
    header = onvif_security_header(user, password) if user else ""
    envelope = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">'
        f"{header}<s:Body>{body}</s:Body></s:Envelope>"
    )

    request = Request(
        url,
        data=envelope.encode(),
        headers={"Content-Type": "application/soap+xml; charset=utf-8"},
        method="POST",
    )

    with urlopen(request, timeout=8) as response:
        return ET.fromstring(response.read())


def command_onvif(ip: str, user: str, password: str) -> None:
    device_url = f"http://{ip}/onvif/device_service"
    print(f"Asking {device_url} ...")

    root = soap(
        device_url,
        '<GetCapabilities xmlns="http://www.onvif.org/ver10/device/wsdl">'
        "<Category>Media</Category></GetCapabilities>",
        user,
        password,
    )

    media_url = None
    for element in root.iter():
        if element.tag.endswith("}XAddr") and element.text and "edia" in (element.text or ""):
            media_url = element.text.strip()
            break

    if media_url is None:
        # Some cameras only return the media address from GetServices.
        media_url = f"http://{ip}/onvif/media_service"

    print(f"Media service: {media_url}")

    profiles = soap(
        media_url,
        '<GetProfiles xmlns="http://www.onvif.org/ver10/media/wsdl"/>',
        user,
        password,
    )

    tokens = []
    for element in profiles.iter():
        if element.tag.endswith("}Profiles"):
            token = element.get("token")
            name = ""
            width = height = codec = ""
            for child in element.iter():
                if child.tag.endswith("}Name") and not name:
                    name = child.text or ""
                if child.tag.endswith("}Width"):
                    width = child.text or ""
                if child.tag.endswith("}Height"):
                    height = child.text or ""
                if child.tag.endswith("}Encoding"):
                    codec = child.text or ""
            tokens.append((token, name, width, height, codec))

    if not tokens:
        print("No media profiles returned. The camera may need a login.")
        return

    for token, name, width, height, codec in tokens:
        uri_reply = soap(
            media_url,
            '<GetStreamUri xmlns="http://www.onvif.org/ver10/media/wsdl">'
            '<StreamSetup><Stream xmlns="http://www.onvif.org/ver10/schema">RTP-Unicast</Stream>'
            '<Transport xmlns="http://www.onvif.org/ver10/schema"><Protocol>RTSP</Protocol></Transport>'
            f"</StreamSetup><ProfileToken>{token}</ProfileToken></GetStreamUri>",
            user,
            password,
        )

        uri = ""
        for element in uri_reply.iter():
            if element.tag.endswith("}Uri") and element.text:
                uri = element.text.strip()
                break

        print(f"\nProfile {name or token}: {width}x{height} {codec}")
        print(f"  RTSP: {uri}")
        if user and uri and "@" not in uri:
            parts = urlsplit(uri)
            with_login = urlunsplit(
                (parts.scheme, f"{user}:{password}@{parts.netloc}", parts.path, parts.query, parts.fragment)
            )
            print(f"  with login: {with_login}")


def ffprobe_ok(url: str) -> str | None:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-rtsp_transport", "tcp",
            "-show_entries", "stream=codec_type,codec_name,width,height,avg_frame_rate",
            "-of", "csv=p=0", url,
        ],
        capture_output=True,
        text=True,
        timeout=12,
    )
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip().replace("\n", " | ")
    return None


def command_guess(ip: str, user: str, password: str) -> None:
    login = f"{user}:{password}@" if user else ""

    for port in (554, 8554, 5544, 10554):
        print(f"\nPort {port}:")
        for path in COMMON_PATHS:
            path = path.format(user=user, password=password)
            url = f"rtsp://{login}{ip}:{port}{path}"
            shown = f"rtsp://{user + ':***@' if user else ''}{ip}:{port}{path}"
            try:
                info = ffprobe_ok(url)
            except subprocess.TimeoutExpired:
                print(f"  timeout  {shown}")
                continue
            if info:
                print(f"  WORKS    {shown}\n           {info}")
            else:
                print(f"  no       {shown}")


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in ("discover", "onvif", "guess"):
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]

    if command == "discover":
        command_discover()
        return

    if len(sys.argv) < 3:
        print(f"usage: find_camera.py {command} IP [user] [password]")
        sys.exit(1)

    ip = sys.argv[2]
    user = sys.argv[3] if len(sys.argv) > 3 else ""
    password = sys.argv[4] if len(sys.argv) > 4 else ""

    if command == "onvif":
        try:
            command_onvif(ip, user, password)
        except Exception as error:  # noqa: BLE001 - report, do not crash
            print(
                f"\nONVIF request failed: {error.__class__.__name__}: {error}\n"
                "Either this host is not an ONVIF camera, ONVIF is switched off "
                "in its web UI, or the login is wrong. Try the web UI at "
                f"http://{ip}/ or run the 'guess' command instead."
            )
            sys.exit(1)
    else:
        command_guess(ip, user, password)


if __name__ == "__main__":
    main()
