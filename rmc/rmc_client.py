# package imports
from rmc_common import *

from auth.client import tcp_client
from auth.crypt import passkey, Fernet
from auth.keys import PrivateKey

import psycopg2

# built-in imports
from pathlib import Path
from ipaddress import ip_address, ip_network
import sys

import datetime
from multiprocessing import Process, Queue
import multiprocessing


"""
Client app:
    - Client: main app
    - Client setup: setup guide window
    - Client auth: authorization form to kick off server authentication
"""

# gui
class Client(UI_Common):
    """ Client window """

    context = 'client'
    subnet = '9.0.0.0/24'
    auth_port = 51820 # TODO: Test on 51820 instead
    wg_port = 51820

    def __init__(self, app, parent=None):
        super().__init__(app, parent=parent)

        self.setWindowTitle("Resolve Mission Control Client")

        # Define buttons
        self.b_dbcon = QPushButton("⇄")
        self.p_LU.lay.addWidget(self.b_dbcon)
        self.b_dbcon.setObjectName("b_dbcon")
        self.b_dbcon.setStyleSheet("""QPushButton#b_dbcon {
                                    color: #848484;
                                    background: transparent;
                                    }
                                    QPushButton#b_dbcon::hover{
                                    	color: white;
                                    }
                                    QPushButton#b_dbcon::pressed{
                                    	color: #848484;
                                    }""")


        self.b_setup = QPushButton("Setup")
        self.b_tunn = QPushButton("Activate Tunnel")
        self.b_sync = QPushButton("Sync Status")

        for b in [self.b_setup, self.b_tunn, self.b_sync]:
            self.p_RU.lay.addWidget(b)

        """TODO:
                - b_tunn should activate the Wireguard tunnel automatically
                - b_sync should open a window which shows the media sync status
        """
        self.b_tunn.setEnabled(False)
        self.b_sync.setEnabled(False)

        # Resolve database views
        self.resolvedb_connect = False

        self.message = QLabel("")
        self.message.setTextFormat(Qt.MarkdownText)
        self.p_RB.lay.addWidget(self.message, alignment=Qt.AlignBottom)

        # BUTTON CONNECT
        self.setup_window = ClientSetup(self)
        self.b_setup.clicked.connect(self.setup_window.show)
        self.b_dbcon.clicked.connect(self.database_connect)

    def auth_client(self):
        """ Authorize client over TCP with the RMC Server """
        auth_request = ClientAuth(self)
        auth_request.setWindowTitle("Authenticate")

        auth_result = auth_request.exec_()
        auth_request = auth_request.get_output()

        if auth_result:

            try:
                ip_address(auth_request['S_IP'])
            except ValueError as e:
                UI_Error(self,"Invalid Server IP", str(e))
                self.auth_client()
                return

            try:
                int(auth_request['S_PORT'])
            except ValueError as e:
                UI_Error(self,"Invalid Server Port", str(e))
                self.auth_client()
                return

            if len(auth_request['S_PWD']) == 0:
                UI_Error(self,"Invalid Server Password",
                            "Input string length zero")
                self.auth_client()
                return

            elif len(auth_request['UNAME']) == 0:
                UI_Error(self,"Invalid Username", "Input string length zero")
                self.auth_client()
                return

            self.auth_request = auth_request

            # By this point, the input is a valid authentication request
            auth_tcp = ClientAuthTCP(self)
            auth_tcp.exec_()
            if auth_tcp.tcp_authentic:

                # Create Wireguard tunnel config file
                PKEYS, IP_ASSIGNED, WG_PORT = auth_tcp.tcp_authentic

                client_config = (f"""
[Interface]
# This MUST match the "AllowedIPs" IP you assigned to this peer in
# the server's config.
Address = {IP_ASSIGNED}/32
# Substitute with *this peer's* private key.
PrivateKey = {auth_tcp.pk}
# This prevents IPv4 & IPv6 DNS leaks when browsing the web on the VPN
DNS = 1.1.1.1, 8.8.8.8, 2001:4860:4860::8888

[Peer]
# Substitute with your *server's* public key
PublicKey = {PKEYS}
# Your Wireguard server's public IP. If you chose a different port
# earlier when setting up port forwarding on your router, update the
# port here to match.
Endpoint = {auth_request['S_IP']}:{WG_PORT}
# Informs Wireguard to forward ALL traffic through the VPN.
AllowedIPs = 0.0.0.0/0, ::/0
# If you're be behind a NAT, this will keep the connection alive.
PersistentKeepalive = 25
                """)

                # Save config to conf file
                saveto = FileDialog(forOpen=False, fmt='conf',
                                    title="Save Wireguard Configuration File")

                if saveto:
                    with open(saveto, 'w') as save_conf:
                        save_conf.write(client_config)

class ClientSetup(QWidget):
    """ Window to help client with setup """

    def __init__(self, client, parent=None):
        super().__init__(parent=parent)
        self.client = client
        self.setWindowTitle("Client Setup")

        self.lay = QGridLayout(self)

        # self.setFrameShape(QtWidgets.QFrame.Panel)
        self.setObjectName("ClientSetup")

        stylesheet  = """QWidget#ClientSetup {"""
        stylesheet += f"""background-color: #28282E;"""
        stylesheet += """}"""
        stylesheet += """QLabel { color: white; }"""

        self.setStyleSheet(stylesheet)
        self.b_setup = {}

        b = self.add_step("Authenticate", link('ui/icons/database_secured.png'), 0,0)
        b.clicked.connect(self.client.auth_client)
        b.setEnabled(True)

        self.add_arrow(0,1)
        b = self.add_step("Connect to Tunnel", link('ui/icons/user_secured.png'), 0,2)
        b.clicked.connect(lambda: ConnectToTunnel(self))

        self.add_arrow(0,3)
        b = self.add_step("Export Database Access Key", link('ui/icons/database_secured.png'), 0,4)
        b.clicked.connect(self.client.dbses.export_selected)
        b.setEnabled(True)

    def add_step(self, label_text, icon, i, j):
        """ Add setup step (button) """

        slay = QHBoxLayout()
        icon = QPixmap(icon)

        key = label_text.lower()

        self.b_setup[key] = QPushButton(label_text)
        self.b_setup[key].setEnabled(False)
        self.b_setup[key].setObjectName("setup_button")
        self.b_setup[key].setStyleSheet(
            """QPushButton#setup_button {
                color: #848484;
                background: transparent;
            }
            QPushButton#setup_button::hover{
            	color: white;
            }
            QPushButton#setup_button::pressed{
            	color: #848484;
            }""")

        icon = icon.scaledToWidth(50, Qt.SmoothTransformation)

        self.b_setup[key].setIcon(QIcon(icon))
        self.b_setup[key].setIconSize(icon.rect().size())

        slay.addWidget(self.b_setup[key])
        self.lay.addWidget(self.b_setup[key], i,j)

        return self.b_setup[key]

    def add_arrow(self, i,j):
        """ Add setup flow arrow """

        arrow = QLabel("→")
        arrow.setObjectName("arrow")
        self.lay.addWidget(arrow, i,j)

def ConnectToTunnel(client):

    text = f"""Use the Wireguard app to connect.
- Click "Import tunnel from file"
- Open the .conf file you saved
- Activate"""

    msg = QMessageBox(client)
    msg.setTextFormat(Qt.MarkdownText)
    msg.setText(text)
    msg.setInformativeText("")
    msg.setWindowTitle("Connect to Tunnel")
    msg.exec_()

# ----------------------- AUTHENTICATION PROMPTS AND FLOWS

class ClientAuth(UI_Dialog):
    """ Form to get client-side authorization details """

    def __init__(self, parent = None):
        super(ClientAuth, self).__init__(parent)

        layout = QVBoxLayout(self)

        self.UNAME = QtWidgets.QLineEdit()
        self.UNAME.setPlaceholderText("Username")

        self.S_IP = QtWidgets.QLineEdit()
        self.S_IP.setPlaceholderText("Server IP")

        self.S_PORT = QtWidgets.QLineEdit()
        self.S_PORT.setPlaceholderText("Server Port")

        self.S_PWD = QtWidgets.QLineEdit()
        self.S_PWD.setPlaceholderText("Server Password")
        self.S_PWD.setEchoMode(QtWidgets.QLineEdit.Password)

        layout.addWidget(self.UNAME)
        layout.addWidget(self.S_IP)
        layout.addWidget(self.S_PORT)
        layout.addWidget(self.S_PWD)

        # OK and Cancel buttons
        buttons = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel,
            Qt.Horizontal, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout.addWidget(buttons)

        if self.parent().config['auth'] != {}:
            auth = self.parent().config['auth']

            self.UNAME.setText(auth['client_username'])
            self.S_PWD.setText(auth['server_password'])
            self.S_IP.setText( auth['server_ip'] )
            self.S_PORT.setText( auth['server_port'] )

    def get_output(self):

        self.auth_request = {
            "UNAME" : self.UNAME.text(),
            "S_IP"  : self.S_IP.text(),
            "S_PORT": self.S_PORT.text(),
            "S_PWD" : self.S_PWD.text(),
        }

        client = self.parent()
        client.config['auth']['client_username'] = self.auth_request['UNAME']
        client.config['auth']['server_password'] = self.auth_request['S_PWD']
        client.config['auth']['server_ip'] = self.auth_request['S_IP']
        client.config['auth']['server_port'] = self.auth_request['S_PORT']
        client.config.save()

        return (self.auth_request)


class ClientAuthTCP(UI_Dialog):
    """ Front-end of TCP Client"""

    def __init__(self, parent = None):
        super(ClientAuthTCP, self).__init__(parent)

        layout = QVBoxLayout(self)

        self.status = QtWidgets.QLabel()
        layout.addWidget(self.status)

        client = self.parent()
        self.status.setText("Creating request")

        # ------------- INPUTS
        S_IP = client.auth_request['S_IP']
        S_PORT = client.auth_request['S_PORT']
        UNAME = client.auth_request['UNAME']
        SPASS = passkey(client.auth_request['S_PWD'])

        # ------------- GENERATE KEYS
        pk = PrivateKey.generate()
        Pk = pk.public_key()
        self.pk = pk  # save for config use

        # ------------- GENERATE PACKET
        MESSG = f"{SPASS.decode()},{Pk}"

        # Authentication request
        encrypted = Fernet(passkey(UNAME)).encrypt(MESSG.encode())

        self.tcp_queue = Queue()
        self.tcp_proc = Process(target = tcp_client,
                                args = (self.tcp_queue, S_IP, S_PORT, SPASS, encrypted,))

        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.update_status)
        self.update_timer.start(500)
        self.tcp_proc.start()

        self.tcp_authentic = None

    def update_status(self):
        if not self.tcp_queue.empty():
            update = self.tcp_queue.get_nowait()

        else:
            if self.tcp_authentic:
                self.close()
            return

        if type(update) == str:
            self.status.setText(update)

        elif type(update) == list:
            # This marks the end of the request, a list of
            # [PKEYS, IP_ASSIGNED, WG_PORT]
            self.tcp_authentic = update

    def closeEvent(self, event):
        self.update_timer.stop()
        self.tcp_proc.terminate()
        self.tcp_proc.join()
        self.tcp_queue.close()

if __name__ == '__main__':
    multiprocessing.freeze_support()

    app = QApplication(sys.argv)

    w = Client(app)
    w.show()

    if len(sys.argv) > 1 and sys.argv[1] == 'setup':
        w.setup_window.show()

    sys.exit(app.exec_())
