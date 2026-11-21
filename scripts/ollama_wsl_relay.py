"""Forward only the course app's Ollama requests from the WSL adapter."""

import argparse
import http.client
from ipaddress import IPv4Address
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Relay(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ('/api/version', '/api/tags'):
            self.send_error(404)
            return
        self.forward()

    def do_POST(self):
        if self.path != '/api/chat':
            self.send_error(404)
            return
        self.forward()

    def forward(self):
        try:
            length = int(self.headers.get('Content-Length', '0'))
        except ValueError:
            self.send_error(400)
            return
        if not 0 <= length <= 1_000_000:
            self.send_error(413)
            return
        upstream = http.client.HTTPConnection('127.0.0.1', 11434, timeout=125)
        try:
            upstream.request(self.command, self.path, body=self.rfile.read(length),
                             headers={'Content-Type': 'application/json'})
            response = upstream.getresponse()
            data = response.read()
        except (OSError, http.client.HTTPException):
            self.send_error(502)
            return
        finally:
            upstream.close()
        self.send_response(response.status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('wsl_gateway', type=IPv4Address)
    args = parser.parse_args()
    if args.wsl_gateway.is_unspecified or not args.wsl_gateway.is_private:
        parser.error('Pass the private IPv4 address of the Windows WSL adapter.')
    ThreadingHTTPServer((str(args.wsl_gateway), 11435), Relay).serve_forever()
