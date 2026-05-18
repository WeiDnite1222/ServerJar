"""
ServerJar

Wei - 2026
"""
import re
import signal
import socketserver
import logging
import os
import queue
import ssl
import sys
import subprocess
import threading
import time
import datetime
import base64
import hmac
from pathlib import Path
import click
import yaml
from utils.common import get_latest_version_minecraft, get_specific_version_paper_builds, \
    download_server_jar, download_latest_build_paper_jar, get_latest_paper_version, download_vanilla_server_jar
from utils.file_settings import FileSettings
from utils.file_settings import required_list, required_value
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization

ROOT_DIR = Path(os.getcwd())
SERVER_CONFIG_PATH = ROOT_DIR / "config" / "server.yml"
VERSION = "1.1"
LOG_DIR_NAME = "logs"
SERVERJAR_LOG_FILE = "serverjar.log"
LOG_DOWNLOAD_CHUNK_SIZE = 4096

def exit(message):
    click.echo(click.style(message, fg='green'))
    sys.exit(0)

@click.group()
def main():
    print(f"ServerJar v{VERSION}"
          f"\nWorkDir: {ROOT_DIR}")


def load_settings():
    s = FileSettings(
        SERVER_CONFIG_PATH,
        {
            "servers": [],
            "socketServerHostname": "127.0.0.1",
            "socketServerPort": 25560,
            "socketServerPassword": ""
        },
        {
            "socketServerHostname": required_value("127.0.0.1"),
            "socketServerPort": required_value(25560),
            "socketServerPassword": required_value(""),
            "enableTLSSupport": required_value(True),
            "socketServerCertfile": required_value("data/server-public.pem"),
            "socketServerKeyfile": required_value("data/server-private.pem"),
            "servers": required_list(
                {
                    "name": "Unnamed Server",
                    "version": "unknown",
                    "description": "",
                    "args": [],
                    "workDir": "",
                    "port": 25565,
                    "host": "127.0.0.1",
                    "enable": True
                },
                use_same_form=True,
            )
        },
        dumps_func=yaml.safe_dump,
        load_func=yaml.safe_load,
    )

    if not s.exists():
        s.create()

    s.read_from_exist()

    return s


@main.command()
@click.option("--name", "-d", default="Unnamed Server", show_default=True, help="Server name")
@click.option("--mc-version", "-m",
              default=None,
              help="Specify Minecraft version to download (If not specified, download latest Minecraft version)",
              required=False)
@click.option("--build", "-b", default=None,
              help="Specify paper build to download (Use latest Minecraft version if not specified)")
@click.option("--server-type", "-t",
              type=click.Choice(["paper", "vanilla"], case_sensitive=False),
              default="paper",
              show_default=True,
              help="Server jar type to download")
@click.option("--snapshot", is_flag=True,
              help="Download snapshot version Minecraft (Use it if the current mc-version type is snapshot)")
@click.option("--latest", is_flag=True, help="Download latest Minecraft version")
@click.option("--list-builds", is_flag=True, help="List available paper build versions")
@click.option("--filename", default=None, help="Custom SERVER.jar file name")
@click.option("--extra-args", "-e",
              help="Extra java arguments", type=str, default="")
@click.option("--custom-args", "-ce",
              help="Custom arguments (command)", type=str, default="")
@click.option("--java-exec-path", "-p", show_default=True,
              help="The destination of the java executable", default="java")
@click.option("--x-memory-initial", "-xms", show_default=True,
              help="Initial allocation size of the memory for server",
              type=str, default="1G")
@click.option("--x-memory-maximum", "-xmx", show_default=True,
              help="Maximum allocation size of the memory for server",
              type=str, default="4G")
@click.option("--nogui", "-ng",
              help="Disable server window",
              is_flag=True)
@click.option("--server-host", "-srh",
              help="Hostname of the server", required=True)
@click.option("--server-port", "-srp",
              help="Port of the server", required=True)
def create_server(name, mc_version, build, server_type, snapshot, latest, list_builds, filename, extra_args, java_exec_path,
                  x_memory_initial, x_memory_maximum, nogui, custom_args, server_port, server_host):
    server_dir = Path("servers", name)
    server_type = server_type.lower()

    def prepare_server_dir():
        if server_dir.exists():
            result = str(input("Found existing server dir. Do you want to overwrite it and continue? [y/N] "))

            if not result.lower() == "y":
                exit("User aborted.")

        server_dir.mkdir(parents=True, exist_ok=True)

    latest_ver = None

    try:
        release = True if not snapshot else False
        if server_type == "vanilla":
            if build:
                raise click.ClickException("--build is only available when --server-type paper is used.")
            if list_builds:
                raise click.ClickException("--list-builds is only available when --server-type paper is used.")

            if latest or mc_version is None:
                click.echo("Fetching latest Minecraft version...")
                mc_version = get_latest_version_minecraft(release=release)

            prepare_server_dir()
            click.echo(f"Downloading Vanilla Minecraft server {mc_version} ...")
            out = download_vanilla_server_jar(mc_version, server_dir, filename=filename)
            click.echo(f"Done: {out}")
        elif latest:
            click.echo("Fetching latest Mojang release version...")
            latest_ver = get_latest_paper_version(release=release)
            builds = get_specific_version_paper_builds(latest_ver)
            prepare_server_dir()
            out = download_server_jar(latest_ver, builds[-1], server_dir)
        else:
            if mc_version is None:
                click.echo("The mc-version is not specified. Fetching latest Minecraft release version...")
                mc_version = get_latest_version_minecraft(release=release)

            if list_builds:
                builds = get_specific_version_paper_builds(mc_version)
                if not builds:
                    click.echo(f"No builds found for Paper {mc_version}")
                    return
                click.echo(f"Paper {mc_version} builds:")
                click.echo(", ".join(map(str, builds[-20:])))
                click.echo("(Only list latest 20 builds)")
                return

            if build:
                click.echo(f"Downloading Paper {mc_version} build {build} ...")
                prepare_server_dir()
                out = download_server_jar(mc_version, str(build), server_dir, filename=filename)
                click.echo(f"Done: {out}")
            else:
                click.echo(f"Downloading latest Paper build for {mc_version} ...")
                prepare_server_dir()
                out = download_latest_build_paper_jar(mc_version, server_dir, filename=filename)
                click.echo(f"Done: {out}")

    except Exception as e:
        raise click.ClickException(str(e))

    settings = load_settings()

    print("There's some information you need to fill for server config.")
    name = str(input("New server name: ")) if name is None else name
    desc = str(input("Server description: "))

    found_exist = False
    for srv in settings["servers"]:
        if name == srv["name"]:
            found_exist = True

    if found_exist:
        result = str(input("WARNING: Found duplicate server name. Would you like to continue? [y/N] "))
        if not result.lower() == "y":
            exit("User aborted.")
            return

    extra_args += "nogui" if nogui else ""
    args = [
        java_exec_path,
        "-Xms{}".format(x_memory_initial),
        "-Xmx{}".format(x_memory_maximum),
        "-jar",
        out.absolute().as_posix(),
        extra_args,
    ]

    if custom_args:
        print("Will use custom commands as replacement.")
        args = custom_args

    print(f"Server command: {' '.join(args)}")

    with settings.edit() as s:
        print("Saving...")
        s["servers"].append({
            "name": name,
            "version": latest_ver if latest_ver is not None else mc_version,
            "description": desc,
            "args": args,
            "workDir": server_dir.absolute().as_posix(),
            "port": server_port,
            "host": server_host,
            "enable": True,
        })

    print("Done")

class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.clients = []
        self.clients_lock = threading.Lock()

class SocketServer:
    def __init__(self, host, port, enable_tls, certfile: Path, keyfile: Path, password: str = ""):
        self.logger = logging.getLogger("SocketServer")
        self.logger.setLevel(logging.INFO)
        self.stdout_handler = logging.StreamHandler(sys.stdout)
        self.stdout_handler.setFormatter(logging.Formatter("%(levelname)s:%(message)s"))
        if not self.logger.handlers:
            self.logger.addHandler(self.stdout_handler)

        # flags
        self.stop_event = threading.Event()

        # Server
        self.host = host
        self.port = port

        self.tcp_server: ThreadedTCPServer | None = None
        self._tcp_thread: threading.Thread | None = None

        self._log_subscribers: set[queue.Queue] = set()
        self._sub_lock = threading.Lock()

        self.command_receivers = {}
        self.enable_tls = enable_tls
        self.certfile = certfile
        self.keyfile = keyfile
        self.password = "" if password is None else str(password)
        self._ssl_context = None

        if self.password and not self.enable_tls:
            self.logger.warning(
                "[SECURITY] socketServerPassword is enabled while TLS is disabled. "
                "Client passwords will be sent in plaintext."
            )

        if self.enable_tls:
            if not self.certfile.exists():
                raise FileNotFoundError("Certfile not found")

            if not self.keyfile.exists():
                raise FileNotFoundError("Keyfile not found")

            self._ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self._ssl_context.load_cert_chain(certfile=self.certfile, keyfile=self.keyfile)

    # -------------------------
    # Socket Server
    # -------------------------
    def publish_log(self, server_name: str, line: str | None = None):
        if line is None:
            log_server = None
            message = server_name
        else:
            log_server = server_name
            message = f"[{server_name}] {line}"

        with self._sub_lock:
            for q in list(self._log_subscribers):
                try:
                    q.put_nowait((log_server, message))
                except queue.Full:
                    pass

    def subscribe_logs(self) -> queue.Queue:
        q = queue.Queue(maxsize=2000)
        with self._sub_lock:
            self._log_subscribers.add(q)
        return q

    def unsubscribe_logs(self, q: queue.Queue):
        with self._sub_lock:
            self._log_subscribers.discard(q)

    def _format_command_help(self, command_map):
        return "\n".join(
            f"[SYS] {command}: {description}"
            for command, description in command_map.items()
        )

    @staticmethod
    def broadcast_all(socks, message):
        for sock in list(socks):
            try:
                sock.sendall((message + "\n").encode("utf-8"))
            except OSError:
                pass

    def get_socket_help_message(self, current_server=None):
        socket_commands = {
            "__help": "Display this help message",
            "__list": "List available server shells",
            "__exit": "Close the current socket connection",
            "__stop_all": "Stop all servers and close the socket server",
            "__c <server name>": "Connect to a server shell",
            "__d": "Disconnect from the current server shell",
            "__sync_log [fromDate:endDate]": "Sync saved log lines from the attached server. Empty syncs the latest 300 lines",
            "__download_log": "Download the attached server's saved log file",
        }
        attached_commands = {
            "__status": "Show target server process status",
            "__stop": "Stop the target server process",
            "__start": "Start the target server process",
            "__restart": "Restart the target server process",
            "__info": "Show server information",
            "<minecraft command>": "Send command to the target Minecraft server process",
        }

        message = "[SYS] ServerJar (Server-side):\n" + self._format_command_help(socket_commands)
        if current_server is not None:
            message += (
                f"\n[SYS] Attached server commands for \"{current_server}\":\n"
                + self._format_command_help(attached_commands)
            )
        else:
            message += "\n[SYS] Use __c <server name> before attached server commands."

        return message

    def get_server_list_message(self):
        if not self.command_receivers:
            return "[SYS] No server shells are available."

        server_names = sorted(self.command_receivers.keys())
        return "[SYS] Available server shells:\n" + "\n".join(
            f"[SYS] - {server_name}" for server_name in server_names
        )

    def handler_command(self, command: str):
        self.logger.info("On...no co", command)

    @staticmethod
    def _send_text(sock, message: str):
        sock.sendall((message + "\n").encode("utf-8"))

    def requires_password(self):
        return bool(self.password)

    def check_password(self, candidate: str):
        return hmac.compare_digest(self.password, candidate)

    def _get_current_server_log_reader(self, current_server):
        if current_server is None:
            return None, "[SYS:ERR] You are not connected to any target server."

        receiver = self.get_command_receiver(current_server)
        if receiver is None:
            return None, f"[SYS:ERR] Target server \"{current_server}\" does not exist."

        log_reader = receiver.get("logReader")
        if not callable(log_reader):
            return None, "[SYS:ERR] Target server's logReader is not callable."

        return log_reader, None

    def send_sync_log(self, sock, current_server, command: str):
        log_reader, error = self._get_current_server_log_reader(current_server)
        if error:
            self._send_text(sock, error)
            return

        date_range = command[len("__sync_log"):].strip()
        try:
            lines = log_reader("sync", date_range)
        except ValueError as e:
            self._send_text(sock, f"[SYS:ERR] {e}")
            return
        except OSError as e:
            self._send_text(sock, f"[SYS:ERR] Unable to read log: {e}")
            return

        if not lines:
            self._send_text(sock, "[SYS] No saved log lines matched.")
            return

        self._send_text(sock, f"[SYS] Syncing {len(lines)} saved log line(s).")
        for line in lines:
            self._send_text(sock, f"[LOG] {line}")

    def send_download_log(self, sock, current_server):
        log_reader, error = self._get_current_server_log_reader(current_server)
        if error:
            self._send_text(sock, error)
            return

        try:
            log_path = log_reader("path")
            if not log_path.exists():
                self._send_text(sock, "[SYS:ERR] No saved log file exists yet.")
                return

            safe_server_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", current_server).strip("._") or "server"
            file_name = f"{safe_server_name}-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}.log"
            self._send_text(sock, f"[DOWNLOAD_LOG_BEGIN] {file_name}")
            with log_path.open("rb") as f:
                while True:
                    chunk = f.read(LOG_DOWNLOAD_CHUNK_SIZE)
                    if not chunk:
                        break
                    self._send_text(sock, base64.b64encode(chunk).decode("ascii"))
            self._send_text(sock, "[DOWNLOAD_LOG_END]")
        except OSError as e:
            self._send_text(sock, f"[SYS:ERR] Unable to download log: {e}")

    def _build_tcp_server(self):
        manager = self

        class TCPServer(ThreadedTCPServer):
            allow_reuse_address = True
            daemon_threads = True

            def __init__(self, server_address, RequestHandlerClass):
                super().__init__(server_address, RequestHandlerClass)
                self.manager = manager

            def get_request(self):
                sock, addr = super().get_request()

                if not self.manager.enable_tls:
                    return sock, addr

                try:
                    tls_sock = self.manager._ssl_context.wrap_socket(sock, server_side=True)
                except ssl.SSLError:
                    sock.close()
                    raise

                return tls_sock, addr

        class Handler(socketserver.BaseRequestHandler):
            current_server_record = {
            }
            def setup(self):
                mgr: Server = self.server.manager

                mgr.logger.info(f"[SYS] Client from {self.client_address[0]}:{self.client_address[1]} connected,")
                with self.server.clients_lock:
                    self.server.clients.append(self.request)

            def finish(self):
                with self.server.clients_lock:
                    try:
                        self.server.clients.remove(self.request)
                    except ValueError:
                        pass
                self.current_server_record.pop(
                    f"{self.client_address[0]}:{self.client_address[1]}",
                    None,
                )
                super().finish()

            def handle(self):
                mgr: Server = self.server.manager

                authenticated = not mgr.requires_password()
                log_q = None
                stop_evt = threading.Event()

                def push_logs():
                    while not stop_evt.is_set():
                        try:
                            log_server, line = log_q.get(timeout=0.5)
                        except Exception:
                            continue
                        current_server = self.current_server_record.get(
                            f"{self.client_address[0]}:{self.client_address[1]}",
                            None,
                        )
                        # Only push client connected server's log
                        if log_server is not None and log_server != current_server:
                            continue
                        try:
                            self.request.sendall(f"[LOG] {line}\n".encode("utf-8"))
                        except OSError:
                            break

                t = None

                try:
                    if authenticated:
                        self.request.sendall(b"[SYS] connected\n")
                        log_q = mgr.subscribe_logs()
                        t = threading.Thread(target=push_logs, daemon=True)
                        t.start()
                    else:
                        self.request.sendall(b"[AUTH_REQUIRED] Password required before continuing.\n")

                    buf = b""

                    while True:
                        data = self.request.recv(4096)
                        if not data:
                            break

                        buf += data
                        while b"\n" in buf:
                            raw, buf = buf.split(b"\n", 1)
                            cmd = raw.decode("utf-8", errors="replace").strip()

                            if not cmd:
                                continue

                            if not authenticated:
                                if cmd == "__exit":
                                    self.request.sendall(b"[SYS] bye\n")
                                    return

                                if cmd.startswith("__auth "):
                                    password = cmd[len("__auth "):]
                                    if mgr.check_password(password):
                                        authenticated = True
                                        self.request.sendall(b"[AUTH_OK] authenticated\n")
                                        self.request.sendall(b"[SYS] connected\n")
                                        log_q = mgr.subscribe_logs()
                                        t = threading.Thread(target=push_logs, daemon=True)
                                        t.start()
                                    else:
                                        mgr.logger.warning(
                                            "[SECURITY] Authentication failed from %s:%s",
                                            self.client_address[0],
                                            self.client_address[1],
                                        )
                                        self.request.sendall(b"[AUTH_ERR] Invalid password.\n")
                                    continue

                                self.request.sendall(b"[AUTH_REQUIRED] Password required before continuing.\n")
                                continue

                            current_server = self.current_server_record.get(
                                f"{self.client_address[0]}:{self.client_address[1]}",
                                None)

                            mgr.logger.info(f"[SYS] Client from {self.client_address[0]}:{self.client_address[1]} send command \"{cmd}\".")

                            ok = None
                            message = None

                            if cmd.startswith("__"):
                                if cmd == "__help":
                                    self.request.sendall(
                                        (mgr.get_socket_help_message(current_server) + "\n").encode("utf-8")
                                    )
                                elif cmd == "__list":
                                    self.request.sendall(
                                        (mgr.get_server_list_message() + "\n").encode("utf-8")
                                    )
                                elif cmd == "__exit":
                                    # Exit socket
                                    self.request.sendall(b"[SYS] bye\n")
                                    return
                                elif cmd == "__stop_all":
                                    self.request.sendall(
                                        f"[SYS] Stopping all servers...bye\n".encode("utf-8")
                                    )
                                    mgr.broadcast_all(mgr.tcp_server.clients, "[SYS] Server stopping... (Stop by remote client)")
                                    mgr.stop_event.set()
                                    return
                                elif cmd.startswith("__sync_log"):
                                    mgr.send_sync_log(self.request, current_server, cmd)
                                elif cmd == "__download_log":
                                    mgr.send_download_log(self.request, current_server)
                                elif cmd.startswith("__c"):
                                    match = re.match(r"^__c\s+(.+)$", cmd)
                                    if match:
                                        server_name = match.group(1).strip()
                                        receiver = mgr.get_command_receiver(server_name)
                                    else:
                                        server_name = None
                                        receiver = None

                                    if receiver is not None:
                                        self.current_server_record[f"{self.client_address[0]}:{self.client_address[1]}"] = server_name
                                        self.request.sendall(
                                            f"[SYS] Connected to server \"{server_name}\" shell.\n".encode(
                                                    "utf-8")
                                        )
                                    else:
                                        self.request.sendall(
                                            f"[SYS:ERR] Target server \"{server_name}\" does not exist.\n".encode(
                                                    "utf-8")
                                        )
                                elif cmd == "__d":
                                    self.current_server_record[f"{self.client_address[0]}:{self.client_address[1]}"] = None
                                    self.request.sendall(
                                        f"[SYS] Disconnected from current server \"{current_server}\"'s shell.\n".encode(
                                            "utf-8")
                                    )
                                else:
                                    if current_server is not None:
                                        receiver = mgr.get_command_receiver(current_server)
                                        func = receiver.get("receiver") if receiver else None

                                        if callable(func):
                                            ok, message = func(cmd)
                                        else:
                                            self.request.sendall(
                                                "[SYS:ERR] Target server's receiver are not callable.\n".encode(
                                                    "utf-8")
                                            )
                                    else:
                                        # "target server" is Minecraft server
                                        self.request.sendall(
                                            "[SYS:ERR] You are not connected to any target server.\n".encode("utf-8")
                                        )
                            else:
                                if current_server is not None:
                                    receiver = mgr.get_command_receiver(current_server)
                                    func = receiver.get("processReceiver") if receiver else None

                                    if callable(func):
                                        ok, message = func(cmd)
                                    else:
                                        self.request.sendall(
                                            "[SYS:ERR] Target server's processReceiver are not callable.\n".encode(
                                                "utf-8")
                                        )
                                else:
                                    # "target server" is Minecraft server
                                    self.request.sendall(
                                        "[SYS:ERR] You are not connected to any target server.\n".encode("utf-8")
                                    )

                            if ok is not None:
                                msg = f"[OK] Command received. {cmd}\n" if ok else "[ERR] An error occurred\n"
                                if message is not None:
                                    msg = msg + message + "\n"
                                self.request.sendall(msg.encode("utf-8"))
                except (ConnectionResetError, OSError):
                    mgr.logger.info(
                        "[SYS] Client disconnected. From {}:{}".format(self.client_address[0], self.client_address[1]))
                finally:
                    stop_evt.set()
                    if log_q is not None:
                        mgr.unsubscribe_logs(log_q)

        return TCPServer((self.host, self.port), Handler)

    def start_socket_server(self):
        if self.tcp_server:
            print("[SOCK] already running")
            return

        self.tcp_server = self._build_tcp_server()

        def loop():
            self.logger.info(f"[SOCK] listening on {self.host}:{self.port}")
            self.tcp_server.serve_forever(poll_interval=0.5)

        self._tcp_thread = threading.Thread(target=loop, daemon=True)
        self._tcp_thread.start()

    def stop_socket_server(self):
        if not self.tcp_server:
            return
        self.logger.info("[SOCK] shutting down")
        self.broadcast_all(self.tcp_server.clients, "[SYS] Server stopping...")
        self.tcp_server.shutdown()
        self.tcp_server.server_close()
        self.tcp_server = None
        if self._tcp_thread and self._tcp_thread.is_alive():
            self._tcp_thread.join(timeout=2)
        self._tcp_thread = None

    def register_command_receiver(self, server_name, receiver, process_receiver, log_reader=None):
        if server_name in self.command_receivers.keys():
            self.logger.warning(f"[SYS] Command receiver name \"{server_name}\" already registered")
        else:
            self.command_receivers[server_name] = {
                "receiver": receiver,
                "processReceiver": process_receiver,
                "logReader": log_reader,
            }

    def get_command_receiver(self, server_name):
        if server_name in self.command_receivers.keys():
            return self.command_receivers[server_name]

        return None

class Server:
    def __init__(self, name, version, description, args, work_dir, port, host, enable):
        self._stdout_thread = None

        # Process
        self.proc: subprocess.Popen | None = None
        self.proc_lock = threading.Lock()

        self.running = False
        self.stopping = False

        # logger
        self.logger = None
        # Ensure all servers name are not duplicated
        if f"Server.{name}" in logging.root.manager.loggerDict:
            index = 1
            name = f"Server.{name}_1"
            while name not in logging.root.manager.loggerDict:
                name = f"Server.{name}_{index}"

        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.INFO)
        self.stdout_handler = logging.StreamHandler(sys.stdout)
        self.stdout_handler.setFormatter(logging.Formatter(f"[%(asctime)s:%(levelname)s:{name}]: %(message)s"))
        self.logger.addHandler(self.stdout_handler)

        # Values from config
        self.name = name
        self.version = version
        self.description = description
        self.args = args
        self.work_dir = work_dir
        self.port = port
        self.host = host
        self.enable = enable
        self.log_dir = Path(self.work_dir) / LOG_DIR_NAME
        self.log_path = self.log_dir / SERVERJAR_LOG_FILE

        self.log_queue = queue.Queue()  # stdout lines
        self._threads: list[threading.Thread] = []
        self.broadcaster = None

    def _append_saved_log(self, line: str):
        self.log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().isoformat(timespec="seconds")
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(f"{timestamp}\t{line}\n")

    @staticmethod
    def _parse_log_date(value: str, *, is_end=False):
        value = value.strip()
        if not value:
            return None

        date_only = re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) is not None
        try:
            parsed = datetime.datetime.fromisoformat(value)
        except ValueError as e:
            raise ValueError(f"Invalid date '{value}'. Use ISO date format, for example 2026-05-17.") from e

        if date_only and is_end:
            return datetime.datetime.combine(parsed.date(), datetime.time.max)
        return parsed

    @staticmethod
    def _split_saved_log_line(raw_line: str):
        raw_line = raw_line.rstrip("\n")
        timestamp, sep, message = raw_line.partition("\t")
        if not sep:
            return None, raw_line

        try:
            parsed = datetime.datetime.fromisoformat(timestamp)
        except ValueError:
            return None, raw_line

        return parsed, f"{timestamp} {message}"

    def read_saved_logs(self, date_range: str = ""):
        if not self.log_path.exists():
            return []

        start = None
        end = None
        date_range = date_range.strip()
        limit = 300 if not date_range else None

        if date_range:
            if ":" not in date_range:
                raise ValueError("Usage: __sync_log fromDate:endDate")
            start_raw, end_raw = date_range.split(":", 1)
            start = self._parse_log_date(start_raw)
            end = self._parse_log_date(end_raw, is_end=True)
            if start and end and start > end:
                raise ValueError("fromDate must be earlier than endDate.")

        matched = []
        with self.log_path.open("r", encoding="utf-8") as f:
            for raw_line in f:
                timestamp, display_line = self._split_saved_log_line(raw_line)
                if start or end:
                    if timestamp is None:
                        continue
                    if start and timestamp < start:
                        continue
                    if end and timestamp > end:
                        continue
                matched.append(display_line)

        if limit is not None:
            return matched[-limit:]

        return matched

    def log_reader(self, action, date_range=""):
        if action == "sync":
            return self.read_saved_logs(date_range)
        if action == "path":
            return self.log_path

        raise ValueError(f"Unknown log action: {action}")

    def start_process(self):
        self.logger.info("Starting process...")

        with self.proc_lock:
            if self.proc and self.proc.poll() is None:
                self.logger.warning("[PROC] already running, skip")
                return

            if len(self.args) == 0:
                raise Exception("[SYS] No arguments provided")

            self.logger.info("[PROC] spawning: %s", " ".join(self.args))
            self.proc = subprocess.Popen(
                self.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                cwd=self.work_dir,
                encoding="utf-8",
                errors="replace"
            )

            self.logger.info(f"[PROC] Process spawned. PID = {self.proc.pid}")

            self._stdout_thread = threading.Thread(target=self._stdout_reader_loop, daemon=True)
            self._stdout_thread.start()

    def publish_log(self, line):
        if self.broadcaster is None:
            return

        self.broadcaster(self.name, line)

    def register_broadcaster(self, broadcaster):
        self.broadcaster = broadcaster

    def _stdout_reader_loop(self):
        self.logger.info("[PROC] stdout reader started")
        while self.running:
            with self.proc_lock:
                proc = self.proc
                out = proc.stdout if proc else None

            if not proc or proc.poll() is not None or not out:
                self.logger.info("[PROC] process ended / stdout closed")
                break

            line = out.readline()
            if not line:
                break

            line = line.rstrip("\n")
            self.logger.info("[PROC] %s", line)
            try:
                self._append_saved_log(line)
            except OSError as e:
                self.logger.warning("[PROC] unable to save log: %s", e)
            self.publish_log(line)

    def send_command(self, command: str) -> bool:
        with self.proc_lock:
            if not self.proc or self.proc.poll() is not None:
                return False
            if not self.proc.stdin:
                return False

            self.proc.stdin.write(command + "\n")
            self.proc.stdin.flush()
            return True

    def stop_process(self, timeout: float = 10.0):
        with self.proc_lock:
            proc = self.proc

        if not proc:
            return

        # Minecraft only
        self.send_command("stop")

        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

        with self.proc_lock:
            self.proc = None

    # -------------------------
    # Manager lifecycle
    # -------------------------
    def start(self):
        if self.running:
            return
        self.running = True
        self.stopping = False

        try:
            self.start_process()
        except Exception:
            self.running = False
            self.stopping = False
            raise

    def stop(self):
        if not self.running:
            return

        self.stopping = True
        self.running = False

        self.stop_process()

    def restart(self):
        if self.running:
            self.stop()

        self.start()

    def is_process_alive(self) -> bool:
        with self.proc_lock:
            return self.proc is not None and self.proc.poll() is None

    def command_receiver(self, command):
        if command == "__help":
            return True, ("__status: Show target server process status\n"
                          "__stop: Stop the target server process\n"
                          "__start: Start the target server process\n"
                          "__restart: Restart the target server process\n"
                          "__info: Show target server process status\n"
                          "<minecraft command>: Send command to the target Minecraft server process")
        elif command == "__status":
            with self.proc_lock:
                pid = self.proc.pid if self.proc else None
            return True, (f"processAlive: {self.is_process_alive()}\n"
                          f"processPID: {pid}\n"
                          f"workdir: {self.work_dir}")
        elif command == "__stop":
            self.stop()
            return True, f"Server \"{self.name}\" process stopped"
        elif command == "__start":
            self.start()
            return True, f"Server \"{self.name}\" process started"
        elif command == "__info":
            return True, (f"serverName: {self.name}\n"
                          f"serverPID: {self.proc.pid}\n"
                          f"description: {self.description}\n"
                          f"arguments: {self.args}\n"
                          f"host: {self.host}\n"
                          f"port: {self.port}\n"
                          f"version: {self.version}\n"
                          f"status: {"Running" if self.is_process_alive() else "Died"}")
        else:
            return False, f"Unknown command: {command}"

    def process_command_receiver(self, command):
        with self.proc_lock:
            if not self.proc or self.proc.poll() is not None:
                return False, "Process is not running."
            if not self.proc.stdin:
                return False, "Process standard input are not available."

            self.proc.stdin.write(command + "\n")
            self.proc.stdin.flush()
            return True, "Command sent."

def load_all_server_from_settings(settings: FileSettings):
    servers = []
    with settings.edit() as s:
        for server_conf in s.get("servers", []):
            servers.append(Server(
                name=server_conf.get("name"),
                version=server_conf.get("version"),
                description=server_conf.get("description"),
                args=server_conf.get("args",[]),
                work_dir=server_conf.get("workDir"),
                port=server_conf.get("port"),
                host=server_conf.get("host"),
                enable=server_conf.get("enable")
            ))

    return servers


@main.command()
@click.option("--keep-running", required=False, help="Keep server running while all Minecraft servers are not running.",
              default=True, show_default=True, flag_value=True)
def runserver(keep_running: bool):
    logger = logging.getLogger(__name__)
    formatter = logging.Formatter('[%(asctime)s:%(levelname)s:runServer]: %(message)s')
    logger.setLevel(logging.INFO)
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    logger.addHandler(stdout_handler)

    # Server
    settings = load_settings()
    servers = load_all_server_from_settings(settings)
    logger.info("{} servers available".format(len(servers)))

    # Socket
    socket_server = SocketServer(settings.get("socketServerHostname", "127.0.0.1"),
                                 settings.get("socketServerPort", 25560),
                                 settings.get("enableTLSSupport", True),
                                 Path(settings.get("socketServerCertfile", "data/server.crt")),
                                 Path(settings.get( "socketServerKeyfile", "data/server.key")),
                                 settings.get("socketServerPassword", ""))

    # Flags
    stop_once = False

    def cleanup():
        nonlocal stop_once
        if stop_once:
            return

        stop_once = True

        for s in servers:
            logger.info("Stopping server {}...".format(s.name))
            s.stop()

        logger.info("Closing socket server...")
        socket_server.stop_socket_server()
        logger.info("Done")

    def sigint_handler(signum, frame):
        logger.info("Caught SIGINT, exiting...")
        cleanup()
        sys.exit(0)

    signal.signal(
        signal.SIGINT,
        sigint_handler
    )

    # Boot server
    if len(servers) != 0:
        logger.info("Starting socket server")
        socket_server.start_socket_server()

        logger.info("Starting server")
        for server in servers:
            if server.enable:
                server.register_broadcaster(socket_server.publish_log)
                socket_server.register_command_receiver(server.name, server.command_receiver,
                                                        server.process_command_receiver,
                                                        server.log_reader)
                try:
                    server.start()
                except Exception as e:
                    logger.error(f"Server {server.name} failed to start: {e}")
                else:
                    logger.info(f"Server {server.name} started.")
            else:
                logger.info(f"Server {server.name} is disabled.")
        try:
            stop = False

            while not stop:
                if socket_server.stop_event.is_set():
                    logger.info("Remote stop event triggered. Stopping...")
                    cleanup()
                    stop = True
                    continue

                for server in list(servers):
                    if server.running and not server.is_process_alive():
                        logger.info(f"Server {server.name} stopped.")
                        server.running = False

                if servers and not any(server.running for server in servers) and not keep_running:
                    cleanup()
                    stop = True
                    continue

                time.sleep(0.5)
        except KeyboardInterrupt:
            logger.info("Stopping server...")
            cleanup()
    else:
        logger.info("No work to do.")

    settings.save()

    logger.info("Stopped!")

@main.command()
def generate_tls_key():
    print("Generating TLS key...")
    key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, u"US"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, u"California"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, u"San Francisco"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"My Dev Org"),
        x509.NameAttribute(NameOID.COMMON_NAME, u"localhost"),
    ])

    cert = x509.CertificateBuilder().subject_name(
        subject
    ).issuer_name(
        issuer
    ).public_key(
        key.public_key()
    ).serial_number(
        x509.random_serial_number()
    ).not_valid_before(
        datetime.datetime.now(datetime.UTC)
    ).not_valid_after(
        # Valid for 1 year
        datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=365)
    ).add_extension(
        x509.SubjectAlternativeName([x509.DNSName(u"localhost")]),
        critical=False,
    ).sign(key, hashes.SHA256())

    private_key = Path("data/server-private.pem")
    public_key = Path("data/server-public.pem")
    private_key.parent.mkdir(parents=True, exist_ok=True)
    public_key.parent.mkdir(parents=True, exist_ok=True)

    with private_key.open("wb") as f:
        f.write(key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        ))

    with public_key.open("wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    print("Private key saved to {}".format(private_key))
    print("Public key saved to {}".format(public_key))
    print("Done.")


if __name__ == "__main__":
    main()
