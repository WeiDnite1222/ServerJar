import argparse
import asyncio
import queue
import ssl
import sys
import threading
import socket
import time
import traceback
from prompt_toolkit import Application
from prompt_toolkit.layout import Layout, HSplit
from prompt_toolkit.widgets import TextArea
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style
from prompt_toolkit.filters import has_focus
from prompt_toolkit.shortcuts import clear as ptk_clear

version = "Beta-1"


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

        # Queue
        self.incoming = queue.Queue()

        # Command History
        self.cmds = []
        self.current_index = None
        self.start_history_flag = False

        @self.kb.add("c-c")
        def closing_kb(event):
            self.shutdown("Ctrl-C (Stopped by user)")

        @self.kb.add("up", filter=has_focus(self.input_area))
        def get_old_cmd(event):
            # check if there's no old command available in the command history list
            if len(self.cmds) < 2:
                return

            # Save entered command to history list
            if not self.start_history_flag:
                self.insert_new_cmd_to_history(self.get_input_area_output())
                self.start_history_flag = True

            # Set current_index to 1 if it's not initiated yet
            if self.current_index is None:
                self.current_index = 0

            # Avoid IndexError when it's the last one command
            if self.current_index >= len(self.cmds)-1:
                return

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

            # Avoid IndexError when it's the last one command
            if self.current_index-1 < 0:
                return

            self.current_index -= 1

            new_cmd = self.cmds[self.current_index]

            self.set_input_area_text(new_cmd)

        @self.kb.add("enter", filter=has_focus(self.input_area))
        def enter_kb(event):
            # Disable history flag
            self.start_history_flag = False

            cmd = self.input_area.text
            self.input_area.text = ""

            # Save command
            self.insert_new_cmd_to_history(cmd)

            if cmd == "_exit":
                self.shutdown("_exit command detected")
                return

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

        cmd_map = {
            "_exit": _shutdown,
            "_c": connect_to_server_parser,
            "_d": disconnect_from_server,
            "_top": _top,
            "_bottom": _bottom,
            "_version": _version,
        }

        for cmd in cmd_map.keys():
            if command.startswith(cmd):
                return_flag = cmd_map[cmd](command)
                return return_flag

        # self._err("Unknown command '%s'" % command)

        return False

    def display_message(self, message):
        self.message_area.text = message

    def get_input_area_output(self):
        return self.input_area.text

    def set_input_area_text(self, text):
        self.input_area.text = text

    def insert_new_cmd_to_history(self, cmd):
        self.cmds.insert(0, cmd)

    class ServerInfoInvalidException(Exception):
        def __init__(self, message, **kwargs):
            super().__init__()
            self.msg = message

        def __str__(self):
            return self.msg

    def arguments_parser(self):
        parser = argparse.ArgumentParser()

        parser.add_argument("-p", "--port", type=int, help="Port number", required=True)
        parser.add_argument('-host', '--host', type=str, help="Hostname", required=True)
        parser.add_argument('-no-tls', '--no-tls', type="store_true", help="Enable TLS support")

        args = parser.parse_args()

        return args

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
            self._log("Type _c host:port to connect. (_d to disconnect)")
            self.connect_event.wait()

            if self.closing_event.is_set():
                break

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
                    context = ssl.create_default_context()
                    s = context.wrap_socket(raw, server_hostname=self.host)

                s.connect((self.host, self.port))

                with self.sock_lock:
                    self.sock = s

                self._log("Remote socket server connected [HOST: {}, PORT: {}]".format(self.host, self.port))

                buffer = ""
                while True:
                    # Receive remote server broadcast message and display it on log area
                    data = s.recv(4096)
                    if not data:
                        raise ConnectionError("Server closed")
                    buffer += data.decode("utf-8", errors="replace")
                    while "\n" in buffer:
                        line, buffer = buffer.split("\n", 1)
                        # ### Use normal log method ###
                        self.log(line)

            except (ConnectionError, OSError) as e:
                if not self.closing_event.is_set():
                    self._warn(f"Disconnected: {e}, retrying...")
                    time.sleep(1)
            except KeyboardInterrupt:
                self._log("Exiting...")
                break
            except Exception as e:
                self._err(f"Unhandled exception: {e}")
                self._err(f"{traceback.format_exc()}")
            finally:
                with self.sock_lock:
                    try:
                        if self.sock:
                            self._log("Closing remote connection (From {}:{})...".format(self.host, self.port))
                            self.sock.close()
                    except Exception as e:
                        self._err(f"Unable to close socket: {e}")
                        pass
                    self.sock = None

                # reset flags
                self.disconnect_event.clear()
                self.connect_event.clear()


    def startup(self):
        self.args = self.arguments_parser()
        self.layout.focus(self.input_area)
        asyncio.create_task(self.consume_incoming())

        self.client_thread.start()


if __name__ == "__main__":
    app = ServerJarClient()
    app.run(pre_run=app.startup)
