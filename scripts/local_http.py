"""A loopback HTTP server for fixtures that binds without a name lookup.

http.server.HTTPServer.server_bind sets server_name from socket.getfqdn(host).
On the macOS CI runner that reverse lookup blocked for about 35 seconds per
bind inside the gate (LLL-805), in every suite that starts a stub server.
Nothing here reads server_name, so take the bound address instead.
"""
import http.server
import socketserver


class LocalHTTPServer(http.server.ThreadingHTTPServer):
    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = host
        self.server_port = port
