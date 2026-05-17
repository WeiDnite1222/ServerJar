"""
ServerJar

Wei - 2026
"""
import re
import shlex
import signal
import socketserver
import logging
import os
import queue
import sys
import subprocess
import threading
import time
from pathlib import Path
import click
import yaml
from utils.common import download_latest_paper_jar, get_latest_version_minecraft, get_specific_version_paper_builds, \
    download_server_jar, download_latest_build_paper_jar
from utils.file_settings import FileSettings
from utils.file_settings import required_list, required_value

ROOT_DIR = Path(os.getcwd())
SERVER_CONFIG_PATH = ROOT_DIR / "config" / "server.yml"


def exit(message):
    click.echo(click.style(message, fg='green'))


@click.group()
def main():
    print("ServerJar\n"
          "WorkDir: {}".format(ROOT_DIR))


@main.command()
@click.option("--name", "-d", default="Unnamed Server", show_default=True, help="Server name")
@click.option("--mc-version", "-m",
              default=None,
              help="Specify Minecraft version to download (If not specified, download latest Minecraft version)",
              required=False)
@click.option("--build", "-b", default=None,
              help="Specify paper build to download (Use latest Minecraft version if not specified)")
@click.option("--snapshot", is_flag=True,
              help="Download snapshot version Minecraft (Use it if the current mc-version type is snapshot)")
@click.option("--latest", is_flag=True, help="Download latest Minecraft version (With latest build paper)")
@click.option("--list-builds", is_flag=True, help="List available paper build versions")
@click.option("--filename", default=None, help="Custom SERVER.jar file name")
def create_server(name, mc_version, build, snapshot, latest, list_builds, filename):
    server_dir = Path("servers", name)

    if server_dir.exists():
        result = str(input("Found existing server dir. Do you want to overwrite it and continue? [y/N] "))

        if not result.lower() == "y":
            exit("User aborted.")

    server_dir.mkdir(parents=True, exist_ok=True)

    try:
        release = True if not snapshot else False
        if latest:
            click.echo("Fetching latest Mojang release version...")
            out = download_latest_paper_jar(server_dir, filename=filename, release=release)
            click.echo(f"Done: {out}")
            return

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
            out = download_server_jar(mc_version, str(build), server_dir, filename=filename)
            click.echo(f"Done: {out}")
        else:
            click.echo(f"Downloading latest Paper build for {mc_version} ...")
            out = download_latest_build_paper_jar(mc_version, server_dir, filename=filename)
            click.echo(f"Done: {out}")

    except Exception as e:
        raise click.ClickException(str(e))


def load_settings():
    s = FileSettings(
        SERVER_CONFIG_PATH,
        {
            "servers": [],
            "socketServerHostname": "127.0.0.1",
            "socketServerPort": 25560
        },
        {
            "socketServerHostname": required_value("127.0.0.1"),
            "socketServerPort": required_value(25560),
            "servers": required_list(
                {
                    "name": "Unnamed Server",
                    "version": "unknown",
                    "description": "",
                    "command": "",
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
@click.option("--server-folder-path", "-sf",
              help="The destination of the folder", required=True)
@click.option("--server-jar-path", "-sp",
              help="The destination of the SERVER.jar", required=True)
@click.option("--socket-server-host", "-srh",
              help="Hostname of the socket server", required=True)
@click.option("--socket-server-port", "-srp",
              help="Port of the socket server", required=True)
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
@click.option("--extra-args", "-e",
              help="Extra java arguments", type=str, default="")
@click.option("--custom-commands", "-cd",
              help="Custom run commands", type=str, default="")
def create_bootstrap(server_folder_path, server_jar_path, socket_server_host, socket_server_port,
                     java_exec_path, x_memory_initial, x_memory_maximum, nogui, extra_args, custom_commands):

    settings = load_settings()

    print("There's some information you need to fill for server config.")
    name = str(input("New server name: "))
    version = str(input("Server version: "))
    desc = str(input("Server description: "))

    found_exist = False
    for srv in settings["servers"]:
        if name == srv["name"]:
            found_exist = True

    if found_exist:
        result = str(input("WARNING: Found duplicate server name. Would you like to continue? [y/N] "))
        if not result.lower() == "y":
            exit("User aborted.")

    extra_args += " nogui" if nogui else ""
    cmd = f"{java_exec_path} -Xms{x_memory_initial} -Xmx{x_memory_maximum} -jar {server_jar_path} {extra_args}"

    if custom_commands:
        print("Will use custom commands as replacement.")
        cmd = custom_commands

    print(f"Server command: {cmd}")

    with settings.edit() as s:
        print("Saving...")
        s["servers"].append({
            "name": name,
            "version": version,
            "description": desc,
            "command": cmd,
            "workDir": server_folder_path,
            "port": socket_server_port,
            "host": socket_server_host,
            "enable": True,
        })

    print("Done")

class SocketServer:
    def __init__(self, host, port):
        self.logger = logging.getLogger("SocketServer")
        self.stdout_handler = logging.StreamHandler(sys.stdout)
        self.stdout_handler.setFormatter(logging.Formatter("%(level)s:%(message)s"))

        # flags
        self.stop_event = threading.Event()

        # Server
        self.host = host
        self.port = port

        self._tcp_server: socketserver.ThreadingTCPServer | None = None
        self._tcp_thread: threading.Thread | None = None

        self._log_subscribers: set[queue.Queue] = set()
        self._sub_lock = threading.Lock()

        self.command_receivers = {}

    # -------------------------
    # Socket Server
    # -------------------------
    def publish_log(self, server_name: str, line: str | None = None):
        if line is None:
            message = server_name
        else:
            message = f"[{server_name}] {line}"

        with self._sub_lock:
            for q in list(self._log_subscribers):
                try:
                    q.put_nowait(message)
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

    def handler_command(self, command: str):
        self.logger.info("On...no co", command)

    def _build_tcp_server(self):
        manager = self

        class TCPServer(socketserver.ThreadingTCPServer):
            allow_reuse_address = True
            daemon_threads = True

            def __init__(self, server_address, RequestHandlerClass):
                super().__init__(server_address, RequestHandlerClass)
                self.manager = manager

        class Handler(socketserver.BaseRequestHandler):
            current_server_record = {
            }
            def setup(self):
                mgr: Server = self.server.manager

                mgr.logger.info(f"[SYS] Client from {self.client_address[0]}:{self.client_address[1]} connected,")

            def handle(self):
                mgr: Server = self.server.manager

                log_q = mgr.subscribe_logs()
                stop_evt = threading.Event()

                def push_logs():
                    while not stop_evt.is_set():
                        try:
                            line = log_q.get(timeout=0.5)
                        except Exception:
                            continue
                        try:
                            self.request.sendall(f"[LOG] {line}\n".encode("utf-8"))
                        except OSError:
                            break

                t = threading.Thread(target=push_logs, daemon=True)
                t.start()

                try:
                    self.request.sendall(b"[SYS] connected\n")
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

                            current_server = self.current_server_record.get(
                                f"{self.client_address[0]}:{self.client_address[1]}",
                                None)

                            mgr.logger.info(f"[SYS] Client from {self.client_address[0]}:{self.client_address[1]} send command \"{cmd}\".")

                            ok = None
                            message = None

                            if cmd.startswith("__"):
                                if cmd == "__exit":
                                    # Exit socket
                                    self.request.sendall(b"[SYS] bye\n")
                                    return
                                if cmd == "__stop_all":
                                    self.request.sendall(
                                        f"[SYS] Stopping all servers...bye\n".encode("utf-8")
                                    )
                                    mgr.stop_event.set()
                                    return
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
                except ConnectionResetError:
                    mgr.logger.info(
                        "[SYS] Client disconnected. From {}:{}".format(self.client_address[0], self.client_address[1]))
                finally:
                    stop_evt.set()
                    mgr.unsubscribe_logs(log_q)

        return TCPServer((self.host, self.port), Handler)

    def start_socket_server(self):
        if self._tcp_server:
            print("[SOCK] already running")
            return

        self._tcp_server = self._build_tcp_server()

        def loop():
            self.logger.info(f"[SOCK] listening on {self.host}:{self.port}")
            self._tcp_server.serve_forever(poll_interval=0.5)

        self._tcp_thread = threading.Thread(target=loop, daemon=True)
        self._tcp_thread.start()

    def stop_socket_server(self):
        if not self._tcp_server:
            return
        self.logger.info("[SOCK] shutting down")
        self._tcp_server.shutdown()
        self._tcp_server.server_close()
        self._tcp_server = None
        if self._tcp_thread and self._tcp_thread.is_alive():
            self._tcp_thread.join(timeout=2)
        self._tcp_thread = None

    def register_command_receiver(self, server_name, receiver, process_receiver):
        if server_name in self.command_receivers.keys():
            self.logger.warning(f"[SYS] Command receiver name \"{server_name}\" already registered")
        else:
            self.command_receivers[server_name] = {
                "receiver": receiver,
                "processReceiver": process_receiver,
            }

    def get_command_receiver(self, server_name):
        if server_name in self.command_receivers.keys():
            return self.command_receivers[server_name]

        return None

class Server:
    def __init__(self, name, version, description, command, work_dir, port, host, enable):
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
        self.stdout_handler.setFormatter(logging.Formatter("[%(asctime)s:%(level)s]: %(message)s"))
        self.logger.addHandler(self.stdout_handler)

        # Values from config
        self.name = name
        self.version = version
        self.description = description
        self.command = command
        self.work_dir = work_dir
        self.port = port
        self.host = host
        self.enable = enable

        self.log_queue = queue.Queue()  # stdout lines
        self._threads: list[threading.Thread] = []
        self.broadcaster = None

    def start_process(self):
        self.logger.info("Starting process...")

        with self.proc_lock:
            if self.proc and self.proc.poll() is None:
                self.logger.warning("[PROC] already running, skip")
                return

            args = shlex.split(self.command)
            if not args:
                raise ValueError(f"Server \"{self.name}\" command is empty.")

            self.logger.info("[PROC] spawning: %s", self.command)

            self.proc = subprocess.Popen(
                args,
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

    def is_process_alive(self) -> bool:
        with self.proc_lock:
            return self.proc is not None and self.proc.poll() is None

    def command_receiver(self, command):
        if command == "__status":
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
                command=server_conf.get("command"),
                work_dir=server_conf.get("workDir"),
                port=server_conf.get("port"),
                host=server_conf.get("host"),
                enable=server_conf.get("enable")
            ))

    return servers


@main.command()
def runserver():
    logger = logging.getLogger(__name__)
    formatter = logging.Formatter('%(asctime)s:%(levelname)s: %(message)s')
    logger.setLevel(logging.INFO)
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    logger.addHandler(stdout_handler)

    # Server
    settings = load_settings()
    servers = load_all_server_from_settings(settings)
    logger.info("{} servers available".format(len(servers)))

    # Socket
    logger.info("Starting socket server")
    socket_server = SocketServer(settings.get("socketServerHostname", "127.0.0.1"),
                                 settings.get("socketServerPort", 25560))
    socket_server.start_socket_server()

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
    logger.info("Starting server")
    for server in servers:
        if server.enable:
            server.register_broadcaster(socket_server.publish_log)
            socket_server.register_command_receiver(server.name, server.command_receiver,
                                                    server.process_command_receiver)
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

            if servers and not any(server.running for server in servers):
                cleanup()
                stop = True
                continue

            time.sleep(0.5)
    except KeyboardInterrupt:
        logger.info("Stopping server...")
        cleanup()

    logger.info("Stopped!")


if __name__ == "__main__":
    main()
