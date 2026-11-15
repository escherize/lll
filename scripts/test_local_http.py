"""Fixture HTTP servers must bind without a reverse name lookup (LLL-805)."""
from pathlib import Path
import re
import socket
import unittest
from unittest import mock

from local_http import LocalHTTPServer
import http.server

SCRIPTS = Path(__file__).resolve().parent


class LocalHTTPServerTest(unittest.TestCase):
    def test_bind_makes_no_name_lookup(self):
        with mock.patch.object(socket, 'getfqdn', side_effect=AssertionError('getfqdn called')):
            server = LocalHTTPServer(('127.0.0.1', 0), http.server.BaseHTTPRequestHandler)
        try:
            self.assertEqual(server.server_name, '127.0.0.1')
            self.assertEqual(server.server_port, server.server_address[1])
        finally:
            server.server_close()

    def test_no_fixture_constructs_the_stock_server(self):
        stock = re.compile(r'\b(?:Threading)?HTTPServer\(')
        offenders = []
        for path in sorted([*SCRIPTS.glob('*.py'), *SCRIPTS.glob('*.sh')]):
            if path.name in ('local_http.py', 'test_local_http.py'):
                continue
            for number, line in enumerate(path.read_text(errors='replace').splitlines(), 1):
                if stock.search(line.replace('LocalHTTPServer(', '')):
                    offenders.append(f'{path.name}:{number}')
        self.assertEqual(offenders, [], 'use local_http.LocalHTTPServer; the stock bind calls socket.getfqdn')


if __name__ == '__main__':
    unittest.main()
