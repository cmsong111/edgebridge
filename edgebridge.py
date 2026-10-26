#
# Copyright 2021, 2022, 2023 Todd Austin
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file
# except in compliance with the License. You may obtain a copy of the License at:
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed under the
# License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND,
# either express or implied. See the License for the specific language governing permissions
# and limitations under the License.
#
# DESCRIPTION
#
# Forwarding Bridge Server to support Samsung SmartThings Edge drivers running on a SmartThings hub
#
# Features:
#   1. forward HTTP GET/POST/PUT requests from SmartThings hub Edge driver & return response
#   2. forward HTTP requests from IOT device to Edge drivers
#
# Reads configuration from environment variables, optionally loaded from a '.env' file
# Creates and updates '.registrations' file for maintaining Edge driver registration list
#
VERSION = '1.2318101200'

import http.server
import ipaddress
import json
import logging
import os
import platform
import re
import signal
import socket
import sys
from urllib.parse import urlsplit

import requests

ENVFILENAME = '.env'
REGSFILENAME = '.registrations'
DEFAULT_LOGFILE = 'edgebridge.log'
DEFAULT_SERVERPORT = 8088
DEFAULT_FWTIMEOUT = 5
MAXPORT = 65535
TOKEN_LENGTH = 36
HUB_ERROR_LIMIT = 3
HTTP_OK = 200
SMARTTHINGS_API_HOST = 'api.smartthings.com'
FORWARD_METHODS = ('GET', 'POST', 'PUT')
IGNORED_HEADERS = ('user-agent', 'host', 'te', 'connection')
EDGEID_PATTERN = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
LOG_FORMAT = '%(asctime)s %(levelname)-7s %(message)s'
LOG_DATEFMT = '%Y-%m-%d %H:%M:%S'
LEVEL_COLORS = {'DEBUG': '\033[2m', 'INFO': '\033[32m', 'WARNING': '\033[33m', 'ERROR': '\033[31m'}

SERVER_IP = ''
SERVER_PORT = DEFAULT_SERVERPORT
SMARTTHINGS_TOKEN = ''
FWTIMEOUT = DEFAULT_FWTIMEOUT

registrations = []
hubsenderrors = {}
regdeletelist = []
log = logging.getLogger('edgebridge')


class ColorFormatter(logging.Formatter):

    # Color only the level name; the message keeps the terminal's default color so it stays readable
    def formatMessage(self, record):

        line = super().formatMessage(record)
        color = LEVEL_COLORS.get(record.levelname)
        if color:
            line = line.replace(record.levelname, f'{color}{record.levelname}\033[0m', 1)
        return line


def setup_logging(toconsole, tofile, filename, debug):

    log.setLevel(logging.DEBUG if debug else logging.INFO)
    log.addHandler(logging.NullHandler())

    if toconsole:
        console = logging.StreamHandler(sys.stdout)
        # Colors only on an interactive terminal; docker logs and redirected output stay plain text
        formatter = ColorFormatter if sys.stdout.isatty() else logging.Formatter
        console.setFormatter(formatter(LOG_FORMAT, LOG_DATEFMT))
        log.addHandler(console)

    if tofile:
        logfile = logging.FileHandler(filename, mode='w', encoding='utf-8')
        logfile.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATEFMT))
        log.addHandler(logfile)


def http_response(server, code, responsetosend):

    body = responsetosend.encode('utf-8')

    try:
        server.send_response(code)
        if body:
            server.send_header('Content-Type', 'text/xml; charset="utf-8"')
            server.send_header('Content-Length', str(len(body)))
        server.end_headers()
        server.wfile.write(body)
        log.debug('Response sent')
    except OSError:
        log.error(f'HTTP Send error sending response: {responsetosend}')


def build_headers(server, url):

    sentheaders = [key.lower() for key in server.headers.keys()]
    headers = {key: value for key, value in server.headers.items() if key.lower() not in IGNORED_HEADERS}

    # Only attach our token to genuine SmartThings API requests, never to other hosts
    if urlsplit(url).hostname == SMARTTHINGS_API_HOST:
        if 'authorization' not in sentheaders and SMARTTHINGS_TOKEN:
            headers['Authorization'] = SMARTTHINGS_TOKEN

    headers['Host'] = urlsplit(url).netloc

    if 'accept' not in sentheaders:
        headers['Accept'] = '*/*'

    headers['User-Agent'] = 'SmartThings Edge Hub'

    if server.data_bytes:
        headers['Content-Length'] = str(len(server.data_bytes))

    return headers


def proc_forward(server, method, query):

    if not query.startswith('url='):
        log.error('Missing URL from forward command')
        http_response(server, 400, '')
        return

    url = query[4:]
    if urlsplit(url).scheme not in ('http', 'https') or not urlsplit(url).netloc:
        log.error(f'Invalid URL in forward command: {url}')
        http_response(server, 400, '')
        return

    if method not in FORWARD_METHODS:
        log.error(f'Unsupported method for forward command: {method}')
        http_response(server, 405, '')
        return

    log.info(f'Sending {method} to {url}')

    headers = build_headers(server, url)
    log.debug(f'Headers: {headers}')
    if server.data_bytes:
        log.debug(f'Body: {server.data_bytes.decode("utf-8", "replace")}')

    try:
        r = requests.request(method, url, data=server.data_bytes, headers=headers, timeout=FWTIMEOUT)
    except requests.Timeout:
        log.error('Internet request timed out')
        http_response(server, 502, '')
        return
    except requests.RequestException as error:
        log.error(f'Internet request failed: {error}')
        http_response(server, 502, '')
        return

    if r.status_code == HTTP_OK:
        log.debug(f'Returned data: {r.text}')
        http_response(server, HTTP_OK, r.text)
        log.info(f'Response returned to Edge driver (bytes len={len(r.text.encode("utf-8"))})')
    else:
        log.warning(f'HTTP error returned: {r.status_code}')
        http_response(server, r.status_code, '')


def record_hub_error(hubaddr):

    key = f'{hubaddr[0]}:{hubaddr[1]}'
    hubsenderrors[key] = hubsenderrors.get(key, 0) + 1

    if hubsenderrors[key] >= HUB_ERROR_LIMIT:
        del hubsenderrors[key]
        for item in registrations:
            if item['hubaddr'] == hubaddr:
                regdeletelist.append(item)


def passto_hub(server, regrecord):

    hubaddr = f"{regrecord['hubaddr'][0]}:{regrecord['hubaddr'][1]}"

    devip, devport = regrecord['devaddr']
    devaddr = f'{devip}:{devport}' if devport is not None else devip

    url = f'http://{hubaddr}/{devaddr}/{server.command}{server.path}'
    headers = {'Host': hubaddr}

    if server.data_bytes:
        headers['Content-Length'] = str(len(server.data_bytes))
        if 'Content-Type' in server.headers:
            headers['Content-Type'] = server.headers['Content-Type']

    log.info(f'Sending POST: {url} to {hubaddr}')

    try:
        r = requests.post(url, headers=headers, data=server.data_bytes, timeout=FWTIMEOUT)
    except requests.RequestException:
        log.error(f"FAILED sending message to Edge hub {regrecord['hubaddr']}")
        record_hub_error(regrecord['hubaddr'])
        return

    if r.status_code == HTTP_OK:
        log.info(f"Message forwarded to Edge ID {regrecord['edgeid']}")
    else:
        log.error(f"ERROR sending message to Edge hub {regrecord['hubaddr']}: {r.status_code}")


def verify_addr(addrstr):

    if not addrstr:
        return None

    ip, sep, port = addrstr.partition(':')

    if sep:
        try:
            port = int(port)
        except ValueError:
            log.error(f'Invalid port number: {port}')
            return None
        if not 1 <= port <= MAXPORT:
            log.error(f'Invalid port number: {port}')
            return None
    else:
        port = None

    try:
        ipaddress.IPv4Address(ip)
    except ValueError:
        log.error(f'Invalid IP address: {ip}')
        return None

    return (ip, port)


def verify_id(edgeid):

    edgeid = edgeid.lower()
    return edgeid if EDGEID_PATTERN.fullmatch(edgeid) else None


def find_reg(reglist, devaddr, edgeid):

    for index, reg in enumerate(reglist):
        if reg['devaddr'] == devaddr and reg['edgeid'] == edgeid:
            return index

    return None


def read_regs(regs_filename):

    try:
        with open(regs_filename) as f:
            reglist = [json.loads(line) for line in f if line.strip()]
    except FileNotFoundError:
        log.info('No existing registrations')
        return []
    except (OSError, ValueError) as error:
        log.error(f'Error reading registrations: {error}')
        return []

    # JSON stores the address tuples as lists; restore them so they compare equal to new registrations
    for reg in reglist:
        reg['devaddr'] = tuple(reg['devaddr'])
        reg['hubaddr'] = tuple(reg['hubaddr'])

    return reglist


def write_regs(regs_filename, reglist):

    try:
        with open(regs_filename, 'w') as f:
            for reg in reglist:
                f.write(json.dumps(reg) + '\n')
    except OSError:
        log.error('Error saving registrations')


def proc_register(server, method, arglist):

    devaddr = hubaddr = edgeid = None

    for arg in arglist:
        key, _, value = arg.partition('=')
        if key == 'devaddr':
            devaddr = verify_addr(value)
        elif key == 'hubaddr':
            hubaddr = verify_addr(value)
        elif key == 'edgeid':
            edgeid = verify_id(value)
        else:
            log.error('Unrecognized argument in register command')
            http_response(server, 400, '')
            return

    if not (devaddr and hubaddr and edgeid) or hubaddr[1] is None:
        log.error('Missing argument(s) in register command')
        http_response(server, 400, '')
        return

    index = find_reg(registrations, devaddr, edgeid)

    if method == 'POST':
        log.info(f'Request to register device at {devaddr}')
        record = {'devaddr': devaddr, 'edgeid': edgeid, 'hubaddr': hubaddr}

        if index is None:
            registrations.append(record)
            log.info('Registration record ADDED')
        else:
            registrations[index] = record
            log.info('Existing registration was REPLACED')

    elif method == 'DELETE':
        log.info(f'Request to remove registration {devaddr}')

        if index is None:
            log.warning(f'Request to remove address that is not registered: {devaddr}')
            http_response(server, 404, '')
            return

        del registrations[index]
        log.info(f'Registration {index} DELETED')

    else:
        log.error(f'Invalid method provided ({method}) for register command')
        http_response(server, 405, '')
        return

    http_response(server, HTTP_OK, '')
    log.info(f'Updated registrations: {registrations}')
    write_regs(REGSFILENAME, registrations)


def handle_requests(server):

    path, sep, query = server.path.partition('?')

    if not sep:
        log.error('Unregistered address or Invalid endpoint')
        http_response(server, 400, '')
        return

    endpoint = path.split('/')

    if len(endpoint) < 3 or endpoint[1].lower() != 'api':
        log.error('Not an API request')
        http_response(server, 404, '')
        return

    command = endpoint[2].lower()

    if command == 'forward':
        proc_forward(server, server.command, query)
    elif command == 'register':
        proc_register(server, server.command, query.split('&'))
    else:
        log.warning('Invalid endpoint')
        http_response(server, 404, '')


def proc_registered_requests(server):

    clientip, clientport = server.client_address[:2]

    # First see if this is a message from any registered devices
    matches = [record for record in registrations
               if record['devaddr'][0] == clientip and record['devaddr'][1] in (None, clientport)]

    if not matches:
        return False

    for record in matches:
        log.info('>>>>> Forwarding to SmartThings hub')
        passto_hub(server, record)

    http_response(server, HTTP_OK, '')

    # update registration list if exceeded pass-to-hub error threshold for any of the registration records
    # -- this ensures that old no-longer-used ip:port hub addresses get scrubbed from list
    if regdeletelist:
        for item in regdeletelist:
            log.info(f'Scrubbing registration record: {item}')
        registrations[:] = [reg for reg in registrations if reg not in regdeletelist]
        write_regs(REGSFILENAME, registrations)
        regdeletelist.clear()

    return True


def proc_msg(server):

    log.info('**********************************************************************************')
    log.info(f'{server.command} request received from: {server.client_address}')
    log.debug(f'Endpoint: {server.path}')

    server.data_bytes = None
    if 'Content-Length' in server.headers:
        server.data_bytes = server.rfile.read(int(server.headers['Content-Length']))

    if not proc_registered_requests(server):
        handle_requests(server)


class RequestHandler(http.server.BaseHTTPRequestHandler):

    def version_string(self):
        return 'edgeBridge'

    def do_POST(self):

        # If a ping, just send response and don't display any messages
        if '/api/ping' in self.path:
            log.debug('Pingreq')
            http_response(self, HTTP_OK, '')
        else:
            proc_msg(self)

    def do_PUT(self):
        proc_msg(self)

    def do_GET(self):
        proc_msg(self)

    def do_DELETE(self):
        proc_msg(self)

    def log_message(self, format, *args):
        return


def load_dotenv(filename):

    # Minimal .env reader (KEY=VALUE lines); variables already set in the environment take precedence
    try:
        with open(filename) as f:
            lines = f.readlines()
    except OSError:
        return

    for line in lines:
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


def env_str(name, default=''):
    return os.environ.get(name, '').strip() or default


def env_bool(name, default):

    value = env_str(name).lower()
    if not value:
        return default
    return value in ('yes', 'true', 'on', '1')


def env_int(name, default, minimum, maximum):

    value = env_str(name)
    if not value:
        return default

    try:
        number = int(value)
        if minimum <= number <= maximum:
            return number
    except ValueError:
        pass

    log.warning(f'Invalid {name} ({value}); using default: {default}')
    return default


def process_config():

    global SERVER_IP
    global SERVER_PORT
    global SMARTTHINGS_TOKEN
    global FWTIMEOUT

    setup_logging(toconsole=env_bool('CONSOLE_OUTPUT', True),
                  tofile=env_bool('LOGFILE_OUTPUT', False),
                  filename=env_str('LOGFILE', DEFAULT_LOGFILE),
                  debug=env_bool('DEBUG', False) or '-d' in sys.argv[1:])

    SERVER_IP = env_str('SERVER_IP')
    if SERVER_IP:
        try:
            ipaddress.ip_address(SERVER_IP)
        except ValueError:
            log.warning(f'Invalid SERVER_IP ({SERVER_IP}); listening on all interfaces')
            SERVER_IP = ''

    SERVER_PORT = env_int('SERVER_PORT', DEFAULT_SERVERPORT, 1, MAXPORT)
    FWTIMEOUT = env_int('FORWARDING_TIMEOUT', DEFAULT_FWTIMEOUT, 1, 3600)

    token = env_str('SMARTTHINGS_TOKEN')
    if len(token) == TOKEN_LENGTH:
        SMARTTHINGS_TOKEN = 'Bearer ' + token
    elif token:
        log.warning('Invalid SMARTTHINGS_TOKEN; assumed None')


def detect_ip():

    # Trick to get our IP address
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('8.8.8.8', 80))
            return s.getsockname()[0]
    except OSError:
        return '0.0.0.0'


def shutdown(signum, frame):
    sys.exit(0)


#################################################################################################
##                  MAINLINE
#################################################################################################

def main():

    if platform.system() == 'Windows':
        os.system('color')              # force color text to work in Windows

    load_dotenv(ENVFILENAME)
    process_config()
    registrations.extend(read_regs(REGSFILENAME))

    try:
        httpd = http.server.HTTPServer((SERVER_IP, SERVER_PORT), RequestHandler)
    except OSError as error:
        log.error(f'Cannot initialize server: {error}')
        log.warning(f'Invalid IP address or Port {SERVER_PORT} may be in use by another application')
        sys.exit(1)

    # docker stop / systemctl stop send SIGTERM; exit cleanly instead of waiting to be killed
    signal.signal(signal.SIGTERM, shutdown)

    log.info(f'Forwarding Bridge Server v{VERSION} (for SmartThings Edge)')
    log.info(f' > Serving HTTP on {SERVER_IP or detect_ip()}:{SERVER_PORT}')

    try:
        httpd.serve_forever()    # wait for, and process HTTP requests
    except KeyboardInterrupt:
        log.info('Application interrupted by user')
    finally:
        httpd.server_close()


if __name__ == '__main__':
    main()
