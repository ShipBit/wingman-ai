import socket
import struct
import platform
import binascii
import time
from typing import TYPE_CHECKING
#from api.enums import LogSource, LogType
from api.interface import (
    SettingsConfig,
    SkillConfig,
    WingmanConfig,
    WingmanInitializationError,
)
from skills.skill_base import Skill
from services.printr import Printr

if TYPE_CHECKING:
    from wingmen.wingman import Wingman

printr = Printr()


# Exception for when X-Plane instance is not found
class XPlaneIpNotFound(Exception):
    args = "Could not find any running X-Plane instance in network."


class XPlane(Skill):

    def __init__(
        self,
        config: SkillConfig,
        wingman_config: WingmanConfig,
        settings: SettingsConfig,
        wingman: "Wingman",
    ) -> None:
        super().__init__(
            config=config,
            wingman_config=wingman_config,
            settings=settings,
            wingman=wingman,
        )

        self.x_plane_ip = None
        self.x_plane_port = None
        self.sock = None

    async def validate(self) -> list[WingmanInitializationError]:
        errors = await super().validate()

        return errors

    # Function to find X-Plane IP and port via multicast beacon
    def find_xp(self, wait=3.0):
        MCAST_GRP = '239.255.1.1'  # Standard multicast group
        MCAST_PORT = 49707  # (MCAST_PORT was 49000 for XPlane10)

        # Set up to listen for a multicast beacon
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if platform.system() == 'Windows':
            sock.bind(('', MCAST_PORT))
        else:
            sock.bind((MCAST_GRP, MCAST_PORT))
        mreq = struct.pack("=4sl", socket.inet_aton(MCAST_GRP), socket.INADDR_ANY)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)

        if wait > 0:
            sock.settimeout(wait)

        beacon_data = {}
        while not beacon_data:
            try:
                packet, sender = sock.recvfrom(15000)
                header = packet[0:5]
                if header != b"BECN\x00":
                    print("Unknown packet from " + sender[0])
                    print(str(len(packet)) + " bytes")
                    print(packet)
                    print(binascii.hexlify(packet))
                else:
                    data = packet[5:21]
                    (beacon_major_version, beacon_minor_version, application_host_id,
                    xplane_version_number, role, port) = struct.unpack("<BBiiIH", data)

                    computer_name = packet[21:]
                    computer_name = computer_name.split(b'\x00')[0]
                    (raknet_port, ) = struct.unpack('<H', packet[-2:])
                    if all([beacon_major_version == 1,
                            beacon_minor_version == 2,
                            application_host_id == 1]):
                        beacon_data = {
                            'ip': sender[0],
                            'port': port,
                            'hostname': computer_name.decode('utf-8'),
                            'xplane_version': xplane_version_number,
                            'role': role,
                            'raknet_port': raknet_port
                        }
            except socket.timeout:
                raise XPlaneIpNotFound()

        sock.close()
        return beacon_data

    def init_socket(self):
        # Find the X-Plane instance
        beacon = self.find_xp()
        self.x_plane_ip = beacon['ip']
        self.x_plane_port = beacon['port']
        RECEIVE_PORT = 49010  # Port to receive data from X-Plane

        # Create UDP socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        #self.sock.bind(('', RECEIVE_PORT))

    def get_tools(self) -> list[tuple[str, dict]]:
        tools = [
            (
                "read_aircraft_and_environment_data",
                {
                    "type": "function",
                    "function": {
                        "name": "read_aircraft_and_environment_data",
                        "description": "Reads the aircraft and environment data from the simulator.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "variable": {
                                    "type": "string",
                                    "description": "The variable to read from the simulator.",
                                    "enum": [
                                        "PLANE_ALTITUDE",
                                        "AIRSPEED_TRUE",
                                    ],
                                },
                            },
                            "required": ["variable"],
                        },
                    },
                },
            ),
            (
                "set_aircraft_and_environment_data",
                {
                    "type": "function",
                    "function": {
                        "name": "set_aircraft_and_environment_data",
                        "description": "Sets the aircraft and environment data from the simulator.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "variable": {
                                    "type": "string",
                                    "description": "The variable to set in the simulator.",
                                    "enum": [
                                        "PLANE_ALTITUDE",
                                        "AIRSPEED_TRUE",
                                    ],
                                },
                                "value": {
                                    "type": "integer",
                                    "description": "The value to set in the simulator.",
                                },
                            },
                            "required": ["variable"],
                        },
                    },
                },
            ),
        ]
        return tools

    async def execute_tool(
        self, tool_name: str, parameters: dict[str, any]
    ) -> tuple[str, str]:
        function_response = ""
        instant_response = ""

        if tool_name == "read_aircraft_and_environment_data":
            function_response = await self._read_aircraft_and_environment_data(**parameters)
        if tool_name == "set_aircraft_and_environment_data":
            function_response = await self._set_aircraft_and_environment_data(**parameters)

        return function_response, instant_response

    async def is_summarize_needed(self, tool_name: str) -> bool:
        """Returns whether a tool needs to be summarized."""
        return True

    async def is_waiting_response_needed(self, tool_name: str) -> bool:
        """Returns whether a tool probably takes long and a message should be printet in between."""
        return True

    async def _read_aircraft_and_environment_data(self, variable: str) -> str:
        if not self.x_plane_ip or not self.x_plane_port:
            self.init_socket()

        print(variable)

        # Request current altitude
        #self.request_altitude()

        dataref = 'sim/aircraft/engine/acf_num_engines'
        msg = struct.pack("<4sxii400s", b'RREF',
                        1,                     # Send data # times/second
                        0,                    # include this index number with results
                        dataref.encode('utf-8'))  # remember to encode as bytestring
        self.sock.sendto(msg, (self.x_plane_ip, self.x_plane_port))

        data, addr = self.sock.recvfrom(2048)
        header = data[0:4]
        if header[0:4] != b'RREF':
            raise ValueError("Unknown packet")
        
        idx, value = struct.unpack("<if", data[5:13])
        assert idx == 0
        print("Number of engines is {}".format(int(value)))

        msg = struct.pack("<4sxii400s", b'RREF', 0, 0, b'sim/aircraft/engine/acf_num_engines')
        self.sock.sendto(msg, (self.x_plane_ip, self.x_plane_port))

        # Allow some time to receive the altitude
        #time.sleep(2)

        # Get current altitude
        #current_altitude = self.receive_altitude()
        #print(f"Current Altitude: {current_altitude} meters")

    async def _set_aircraft_and_environment_data(self, variable: str, value: int) -> str:
        pass

    # Function to request current altitude
    def request_altitude(self):
        cmd = b'RREF'
        freq = 1  # Frequency in Hz
        index = 0  # Index for the dataref
        dataref = b"sim/flightmodel/position/y_agl" + (b'\x00' * (400 - len("sim/flightmodel/position/y_agl")))  # Padding to 400 bytes
        msg = struct.pack("<4sxii400s", cmd, freq, index, dataref)
        self.sock.sendto(msg, (self.x_plane_ip, self.x_plane_port))
        print("Requested altitude data reference.")

    # Function to receive altitude data
    def receive_altitude(self):
        while True:
            data, addr = self.sock.recvfrom(2048)
            if data.startswith(b'RREF'):
                _, index, altitude = struct.unpack("<5sif", data[:12])
                return altitude
