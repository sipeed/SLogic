#!/usr/bin/env python3
"""Serve the update pages for local or LAN testing.

    python3 serve.py              http://localhost:8000 (this computer only)
    python3 serve.py --lan        https://<lan-ip>:8443 for other computers

Browsers only allow USB access on secure pages, and a plain http:// LAN
address is not one, so --lan serves HTTPS with a self-signed certificate
(made with openssl on first use, kept in .certs/, covering this computer's
current IPv4 addresses). Each visitor accepts the browser's certificate
warning once. Files are sent with Cache-Control: no-cache.
"""
import argparse
import functools
import http.server
import ipaddress
import socket
import ssl
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CERTS = ROOT / ".certs"


def local_ips():
    ips = {"127.0.0.1"}
    for cmd in (["ip", "-4", "-o", "addr", "show", "scope", "global"], ["hostname", "-I"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True).stdout
        except OSError:
            continue
        for word in out.replace("/", " ").split():
            try:
                if ipaddress.ip_address(word).version == 4 and not word.endswith(".255"):
                    ips.add(word)
            except ValueError:
                pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no packet is sent
            ips.add(s.getsockname()[0])
    except OSError:
        pass
    return sorted(ips)


def certificate(ips):
    key, cert = CERTS / "key.pem", CERTS / "cert.pem"
    names = CERTS / "ips.txt"
    if cert.exists() and names.exists() and names.read_text().split() == ips:
        return key, cert
    CERTS.mkdir(exist_ok=True)
    san = ",".join(["DNS:localhost", *(f"IP:{ip}" for ip in ips)])
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                    "-keyout", str(key), "-out", str(cert), "-days", "825",
                    "-subj", "/CN=SLogic firmware update (test)",
                    "-addext", f"subjectAltName={san}"],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    names.write_text(" ".join(ips))
    return key, cert


class Handler(http.server.SimpleHTTPRequestHandler):
    timeout = 60  # drop idle keep-alive connections

    def end_headers(self):
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


class TLSServer(http.server.ThreadingHTTPServer):
    """HTTPS server that does each TLS handshake in the connection's own thread.

    Wrapping the listening socket instead makes accept() do the handshake, so a
    single connection that never sends its TLS hello (browsers open spare
    connections ahead of time) blocks every other visitor.
    """

    daemon_threads = True

    def __init__(self, address, handler, ctx):
        super().__init__(address, handler)
        self.ctx = ctx

    def finish_request(self, request, client_address):
        request.settimeout(10)
        try:
            tls = self.ctx.wrap_socket(request, server_side=True)
        except OSError:  # handshake failed, timed out or the browser gave up
            return
        try:
            self.RequestHandlerClass(tls, client_address, self)
        finally:
            tls.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lan", action="store_true", help="HTTPS on all interfaces")
    ap.add_argument("--port", type=int)
    args = ap.parse_args()

    handler = functools.partial(Handler, directory=str(ROOT))
    if not args.lan:
        port = args.port or 8000
        server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
        print(f"Serving http://localhost:{port}/  (batch: /batch.html)")
    else:
        port = args.port or 8443
        ips = local_ips()
        key, cert = certificate(ips)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert, key)
        server = TLSServer(("0.0.0.0", port), handler, ctx)
        print("Serving on the LAN (accept the certificate warning once):")
        for ip in ips:
            if ip != "127.0.0.1":
                print(f"  https://{ip}:{port}/          batch: https://{ip}:{port}/batch.html")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
