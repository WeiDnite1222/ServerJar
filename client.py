import argparse
import asyncio
import base64
import binascii
import queue
import shutil
import ssl
import sys
import threading
import socket
import time
import traceback
from pathlib import Path
from prompt_toolkit import Application
from prompt_toolkit.layout import Layout, HSplit
from prompt_toolkit.widgets import TextArea
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from prompt_toolkit.filters import has_focus
from prompt_toolkit.shortcuts import clear as ptk_clear

version = "Beta-1"
SERVER_JAR_DIR = Path.home() / ".serverjar"
CLIENT_CERT_DIR = Path.home() / ".serverjar" / "client" / "cert"
CLIENT_CERT_SUFFIXES = {".pem", ".crt", ".cer"}
CLIENT_HISTORY_FILE = Path.home() / ".serverjar" / "history" / "history.txt"
CLIENT_LOG_DIR = Path.home() / ".serverjar" / "client" / "logs"

def add_client_cert(cert_path):
    source = Path(cert_path).expanduser()

    if not source.exists():
        raise FileNotFoundError(f"{source} does not exist")
    if not source.is_file():
        raise IsADirectoryError(f"{source} is not a file")
    if source.suffix.lower() not in CLIENT_CERT_SUFFIXES:
        allowed = ", ".join(sorted(CLIENT_CERT_SUFFIXES))
        raise ValueError(f"Unsupported certificate suffix '{source.suffix}'. Allowed: {allowed}")

    CLIENT_CERT_DIR.mkdir(parents=True, exist_ok=True)
    target = CLIENT_CERT_DIR / source.name

    if source.resolve() == target.resolve():
        return target

    shutil.copy2(source, target)
    return target


def run_cli_action(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] != "--add-cert":
        return False

    parser = argparse.ArgumentParser(prog=f"{Path(sys.argv[0]).name} --add-cert")
    parser.add_argument("cert_path", help="Path to a PEM/CRT/CER certificate file")
    args = parser.parse_args(argv[1:])

    try:
        target = add_client_cert(args.cert_path)
    except Exception as e:
        print(f"Unable to add certificate: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Certificate added: {target}")
    return True


def create_client_tls_context(log=None, warn=None):
    CLIENT_CERT_DIR.mkdir(parents=True, exist_ok=True)
    context = ssl.create_default_context()
    loaded_certs = []

    for cert_path in sorted(CLIENT_CERT_DIR.iterdir()):
        if not cert_path.is_file() or cert_path.suffix.lower() not in CLIENT_CERT_SUFFIXES:
            continue

        try:
            context.load_verify_locations(cafile=cert_path)
        except ssl.SSLError as e:
            if callable(warn):
                warn(f"Unable to load TLS certificate {cert_path}: {e}")
            continue

        loaded_certs.append(cert_path.name)

    if callable(log):
        if loaded_certs:
            log("Loaded TLS certificate(s): {}".format(", ".join(loaded_certs)))
        else:
            log(f"No custom TLS certificates found in {CLIENT_CERT_DIR}")

    return context


def get_history(log=None, warn=None):
    if not CLIENT_HISTORY_FILE.exists():
        return []

    CLIENT_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)

    if callable(log):
        log("Restoring command history...")

    try:
        with CLIENT_HISTORY_FILE.open("r", encoding="utf-8") as f:
            return [line for line in f.read().splitlines() if line]
    except Exception as e:
        if callable(warn):
            warn(f"Unable to restore command history: {e}")

    return []

def save_history(history, log=None, warn=None):
    CLIENT_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)

    if callable(log):
        log("Saving command history...")

    try:
        with CLIENT_HISTORY_FILE.open("w", encoding="utf-8") as f:
            f.write("\n".join(history))
    except Exception as e:
        if callable(warn):
            warn(f"Unable to save command history: {e}")


class ServerJarClient(Application):
    def __init__(self, **kwargs):
        super().__init__(**kwargs, mouse_support=True)

        # Text style
        self.style = Style.from_dict({
            "log": "bg:#000000 #ffffff",
            "input": "bg:#222222 #ffffff",
            "separator-area": "bg:#000000 #ffffff",
            "message-area": "bg:#111111 #ffffff"
        })
        # Socket
        self.sock = None

        # Args
        self.args = None

        # event
        self.kb = KeyBindings()

        # Areas
        # self.log_lines = []

        # self.log_control = FormattedTextControl(
        #     text=lambda: ANSI("".join(self.log_lines))
        # )

        self.log_area = TextArea(
            style="class:log",
            wrap_lines=True,
        )

        self.separator_area = TextArea(text="=" * 10 + " Enter Command Here " + "=" * 10, height=1,
                                       style="class:separator-area")
        self.message_area = TextArea(height=1, multiline=False, style="class:message-area")
        self.input_area = TextArea(height=1, prompt="> ", style="class:input", multiline=False)

        self.layout = Layout(HSplit([
            self.log_area,
            self.separator_area,
            self.message_area,
            self.input_area,
        ]))

        # Thread
        self.sock_lock = threading.Lock()
        self.closing_event = threading.Event()
        self.client_thread = threading.Thread(target=self.client, daemon=True)
        self.connect_event = threading.Event()
        self.disconnect_event = threading.Event()
        self.auth_required = False

        # Queue
        self.incoming = queue.Queue()

        # Command History
        self.cmds = []
        self.current_index = None
        self.history_draft = ""

        @self.kb.add("c-c")
        def closing_kb(event):
            self.shutdown("Ctrl-C (Stopped by user)")

        @self.kb.add("up", filter=has_focus(self.input_area))
        def get_old_cmd(event):
            # check if there's no old command available in the command history list
            if not self.cmds:
                return

            # Save the current input so Down can restore it after browsing history.
            if self.current_index is None:
                self.history_draft = self.get_input_area_output()
                self.current_index = 0
            elif self.current_index < len(self.cmds) - 1:
                self.current_index += 1

            old_cmd = self.cmds[self.current_index]

            self.set_input_area_text(old_cmd)

        @self.kb.add("down", filter=has_focus(self.input_area))
        def get_new_cmd(event):
            # Check if there's no old command available in the command history list
            if len(self.cmds) < 2:
                return

            # Get new command only working when current_index greater then 0
            if self.current_index is None:
                return

            if self.current_index == 0:
                self.current_index = None
                self.set_input_area_text(self.history_draft)
                return

            self.current_index -= 1

            new_cmd = self.cmds[self.current_index]

            self.set_input_area_text(new_cmd)

        @self.kb.add("enter", filter=has_focus(self.input_area))
        def enter_kb(event):
            cmd = self.input_area.text
            self.input_area.text = ""
            self.current_index = None
            self.history_draft = ""

            if cmd == "_exit":
                self.shutdown("_exit command detected")
                return

            if self.auth_required:
                if cmd == "_d":
                    self.command_parser(cmd)
                    return

                with self.sock_lock:
                    s = self.sock

                if s:
                    try:
                        s.sendall(("__auth " + cmd + "\n").encode("utf-8"))
                        self.display_message("Password sent, waiting for server...")
                    except OSError as e:
                        self._err(f"Send failed: {e}\n")
                else:
                    self._err("The remote server is not connected yet.")
                return

            # Save command
            self.insert_new_cmd_to_history(cmd)

            # if re.match(r"^_[A-Za-z0-9]+(?:$|_.*)", cmd):
            exit_flag = self.command_parser(cmd)

            if exit_flag:
                return

            with self.sock_lock:
                s = self.sock

            if s:
                try:
                    s.sendall((cmd + "\n").encode("utf-8"))
                except OSError as e:
                    self._err(f"Send failed: {e}\n")
            else:
                self._err("The remote server is not connected yet.")

        @self.kb.add("c-w", filter=has_focus(self.input_area))
        def focus_log_area(event):
            self.layout.focus(self.log_area)
            self.display_message("Now focus at log area.")

        @self.kb.add("c-w", filter=has_focus(self.log_area))
        def focus_log_area(event):
            self.layout.focus(self.input_area)
            self.display_message("Now focus at input area.")

        self.key_bindings = self.kb
        self.full_screen = True

        # Host and Port
        self.host = None
        self.port = None

    def command_parser(self, command):
        def connect_to_server(host, port):
            # update target
            self.host = host
            self.port = port

            # trigger connection
            self.disconnect_event.clear()
            self.connect_event.set()

            return True

        def disconnect_from_server(cmd):
            self._log("Disconnecting...")
            self.disconnect_event.set()
            self.connect_event.clear()

            with self.sock_lock:
                s = self.sock

            if s:
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except Exception as e:
                    self._err("An error occurred while shutting down sock: " + str(e))
                try:
                    s.close()
                except Exception as e:
                    self._err("An error occurred while closing the socket: {}".format(e))
            elif self.connect_event.is_set():
                self.host = None
                self.port = None
                self._log("Auto-reconnect stopped.")
            else:
                self._err("The remote server is not connected yet.")

            return True

        def connect_to_server_parser(cmd):
            target = cmd[3:].strip()
            try:
                host, port_str = target.split(":", 1)
                host = host.strip()
                port = int(port_str.strip())

                if not host:
                    raise ValueError("empty host")
            except Exception as _:
                self._err("Usage: _c host:port")
                return True

            connect_to_server(host, port)

            return True

        def _shutdown(cmd):
            self.shutdown("_exit command detected")
            return True

        def _top(cmd):
            self.log_area.buffer.cursor_position = 0
            self.invalidate()
            return True

        def _bottom(cmd):
            self.log_area.buffer.cursor_position = len(self.log_area.buffer.text)
            self.invalidate()
            return True

        def _version(cmd):
            self._log("ServerJar Client Version {}".format(version))
            return True

        def _help(cmd):
            for key, value in cmd_map.items():
                self._log(f"{key}: {value.get("description")}")
            return True

        def _clear(cmd):
            self.log_area.text = ""
            self._log("Log cleared")
            return True

        def _clear_history(cmd):
            self.cmds = []
            self.current_index = None
            self.history_draft = ""
            self._log("History cleared")
            return True

        cmd_map = {
            "_exit": {
                "func": _shutdown,
                "description": "Exit the shell",
            },
            "_c": {
                "func": connect_to_server_parser,
                "description": "Connect to the remote server (Usage: _c host:port)",
            },
            "_d": {
                "func": disconnect_from_server,
                "description": "Disconnect from the remote server",
            },
            "_top": {
                "func": _top,
                "description": "Go to the top of the log area",
            },
            "_bottom": {
                "func": _bottom,
                "description": "Go to the bottom of the log area",
            },
            "_version": {
                "func": _version,
                "description": "Display the version of the client",
            },
            "_clear_history": {
                "func": _clear_history,
                "description": "Clear the command history",
            },
            "_clear": {
                "func": _clear,
                "description": "Clear the log area",
            },
            "_help": {
                "func": _help,
                "description": "Display the help message",
            },
        }

        if not command.strip():
            return True

        header = command.split()[0]
        for cmd in cmd_map.keys():
            if cmd == header:
                func = cmd_map.get(cmd).get("func")
                return_flag = func(command)
                return return_flag

        # self._err("Unknown command '%s'" % command)

        return False

    def display_message(self, message):
        self.message_area.text = message

    def get_input_area_output(self):
        return self.input_area.text

    def set_input_area_text(self, text):
        self.input_area.text = text
        self.input_area.buffer.cursor_position = len(text)

    def insert_new_cmd_to_history(self, cmd):
        if not cmd:
            return
        if self.cmds and self.cmds[0] == cmd:
            return
        self.cmds.insert(0, cmd)

    class ServerInfoInvalidException(Exception):
        def __init__(self, message, **kwargs):
            super().__init__()
            self.msg = message

        def __str__(self):
            return self.msg

    def arguments_parser(self):
        parser = argparse.ArgumentParser()

        parser.add_argument("-p", "--port", type=int, help="Port number", required=False)
        parser.add_argument('-host', '--host', type=str, help="Hostname", required=False)
        parser.add_argument('-no-tls', '--no-tls', help="Enable TLS support", action='store_true', default=False,
                            required=False)
        parser.add_argument('-r', '--retry', help="Retry when disconnect", action='store_true', default=False,
                            required=False)
        parser.add_argument('--add-cert', help="Add server certificate", type=str, default=None, required=False)

        args = parser.parse_args()

        return args

    def get_tls_context(self):
        return create_client_tls_context(log=self._log, warn=self._warn)

    def shutdown(self, reason=""):
        if self.closing_event.is_set():
            return

        self.closing_event.set()

        self._log(f"Shutting down for reason: {reason}")

        with self.sock_lock:
            s = self.sock
            if s:
                try:
                    s.close()
                except Exception as e:
                    self._err(f"Unable to close socket: {e}")
                    pass

        # Save history
        save_history(self.cmds, self._log, self._warn)

        # Exit ui event loop
        self.full_exit()

    # @staticmethod
    # def clear_screen():
    #     os.system("cls" if os.name == "nt" else "clear")

    def log(self, message):
        self.incoming.put(f"{message}")

    def _log(self, message):
        # Nothing change
        self.incoming.put(f"[client] {message}")
        # self.display_message(f"{message}")

    def _err(self, message):
        # WIP... (display text as red color if the log is an error message)
        self.incoming.put(f"[client|err] {message}")
        # self.display_message(f"ERROR: {message}")

    def _warn(self, message):
        # WIP... (Display text as yellow color if the log is a warning message)
        self.incoming.put(f"[client|warn] {message}")
        # self.display_message(f"WARNING: {message}")

    def full_exit(self):
        self.exit()
        sys.exit()

    async def consume_incoming(self):
        loop = asyncio.get_running_loop()
        while True:
            msg = await loop.run_in_executor(None, self.incoming.get)

            # self.log_lines.append(msg)
            #
            # if len(self.log_lines) > 2000:
            #     self.log_lines = self.log_lines[-2000:]

            if len(self.log_area.text) > 0:
                self.log_area.text += "\n" + msg
            else:
                self.log_area.text += msg

            if len(self.log_area.text) > 300_000:
                self.log_area.text = "New log start here.\n" + self.log_area.text[-250_000:]

            self.log_area.buffer.cursor_position = len(self.log_area.buffer.text)

            self.invalidate()

    def client(self):
        ptk_clear()


        while not self.closing_event.is_set():
            if self.closing_event.is_set():
                break

            if not self.connect_event.is_set() and (self.args.port is None or self.args.host is None):
                self._log("Type _c host:port to connect. (_d to disconnect)")
                self.connect_event.wait()
            elif self.connect_event.is_set():
                self._log(f"Reconnecting...")
            else:
                self._log(f"Connecting to remote server from {self.args.host}:{self.args.port} (Value from sys.argv)...")
                self.host, self.port = self.args.host, self.args.port

            if not self.host or not self.port:
                self._err("No host/port set. Usage: _c host:port")
                self.connect_event.clear()
                continue

            try:
                self._log(f"Connecting to {self.host}:{self.port} ...")

                # Create connect
                if self.args.no_tls:
                    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    s.connect((self.host, self.port))
                else:
                    raw = socket.create_connection((self.host, self.port))
                    context = self.get_tls_context()
                    s = context.wrap_socket(raw, server_hostname=self.host)

                with self.sock_lock:
                    self.sock = s

                self.auth_required = False
                self._log("Remote socket server connected [HOST: {}, PORT: {}]".format(self.host, self.port))

                buffer = ""
                downloading_log = False
                download_path = None
                download_file = None
                while True:
                    # Receive remote server broadcast message and display it on log area
                    data = s.recv(4096)
                    if not data:
                        raise ConnectionError("Server closed")
                    buffer += data.decode("utf-8", errors="replace")
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        if line.startswith("[AUTH_REQUIRED]"):
                            self.auth_required = True
                            self.display_message("Password required. Type the server password to continue.")
                            self._warn("Server requires a password before continuing.")
                            if self.args.no_tls:
                                self._warn("TLS is disabled. The password will be sent without encryption.")
                            continue

                        if line.startswith("[AUTH_OK]"):
                            self.auth_required = False
                            self.display_message("Authenticated.")
                            self._log("Server password accepted.")
                            continue

                        if line.startswith("[AUTH_ERR]"):
                            self.auth_required = True
                            self.display_message("Invalid password. Try again, or use _d to disconnect.")
                            self._err(line)
                            continue

                        if line.startswith("[DOWNLOAD_LOG_BEGIN]"):
                            if download_file:
                                download_file.close()

                            file_name = line[len("[DOWNLOAD_LOG_BEGIN]"):].strip()
                            file_name = Path(file_name).name or "serverjar.log"
                            CLIENT_LOG_DIR.mkdir(parents=True, exist_ok=True)
                            download_path = CLIENT_LOG_DIR / file_name
                            download_file = download_path.open("wb")
                            downloading_log = True
                            self._log(f"Downloading log to {download_path}")
                            continue

                        if line == "[DOWNLOAD_LOG_END]":
                            if download_file:
                                download_file.close()
                                download_file = None
                            downloading_log = False
                            self._log(f"Log downloaded: {download_path}")
                            download_path = None
                            continue

                        if downloading_log:
                            if line.startswith("["):
                                if line.startswith("[SYS:ERR]"):
                                    if download_file:
                                        download_file.close()
                                        download_file = None
                                    downloading_log = False
                                    download_path = None
                                self.log(line)
                                continue

                            try:
                                if download_file:
                                    download_file.write(base64.b64decode(line.encode("ascii")))
                            except (binascii.Error, OSError) as e:
                                self._err(f"Unable to write downloaded log: {e}")
                                if download_file:
                                    download_file.close()
                                    download_file = None
                                downloading_log = False
                            continue

                        # ### Use normal log method ###
                        self.log(line)

            except (ConnectionError, OSError) as e:
                if not self.closing_event.is_set():
                    if self.args.retry:
                        self._warn(f"Disconnected: {e}, retrying...")
                    else:
                        self._err(f"Disconnected: {e}")
                    time.sleep(1)
            except KeyboardInterrupt:
                self._log("Exiting...")
                break
            except Exception as e:
                self._err(f"Unhandled exception: {e}")
                self._err(f"{traceback.format_exc()}")
            finally:
                if "download_file" in locals() and download_file:
                    download_file.close()

                with self.sock_lock:
                    try:
                        if self.sock:
                            self._log("Closing remote connection (From {}:{})...".format(self.host, self.port))
                            self.sock.close()
                    except Exception as e:
                        self._err(f"Unable to close socket: {e}")
                        pass
                    self.sock = None
                self.auth_required = False

                # reset flags
                self.disconnect_event.clear()
                if not self.args.retry:
                    self.connect_event.clear()


    def startup(self):
        self.args = self.arguments_parser()
        self.layout.focus(self.input_area)
        self.cmds = get_history(self._log, self._warn)
        asyncio.create_task(self.consume_incoming())

        self.client_thread.start()


if __name__ == "__main__":
    if run_cli_action():
        sys.exit(0)

    app = ServerJarClient()
    app.run(pre_run=app.startup)
