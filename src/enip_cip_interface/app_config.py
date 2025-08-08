from pathlib import Path

from pydoover import config

class EnipTagSyncMode(config.Enum):
    FROM_PLC = "Read from PLC"
    TO_PLC = "Write to PLC"
    SYNC_PLC_PREFERRED = "Sync (PLC Preferred)"
    SYNC_DOOVER_PREFERRED = "Sync (Doover Preferred)"

class EnipCipInterfaceConfig(config.Schema):

    def __init__(self):
        self.port = config.Integer("Port", default=44818, description="The port to host an ENIP server on")
        self.enable_enip_server = config.Boolean("Enable ENIP Server", default=False, description="Whether to enable the ENIP server")
        self.tag_namespace_separator = config.String("Tag Namespace Separator", default="__", description="The separator to use between tag namespaces")
        self.plcs = config.Array("PLCs", element=self.construct_plc(), description="The PLCs to connect to")

    def construct_plc(self):
        plc_tag_mapping = config.Object("PLC Tag Mapping")
        plc_tag_mapping.add_elements(
            config.Enum(
                "Mode",
                default=EnipTagSyncMode.FROM_PLC,
                description="The mode to use for the PLC tag mapping",
                choices=[
                    EnipTagSyncMode.FROM_PLC,
                    EnipTagSyncMode.TO_PLC,
                    EnipTagSyncMode.SYNC_PLC_PREFERRED,
                    EnipTagSyncMode.SYNC_DOOVER_PREFERRED,
                ]
            ),
            config.String("Doover Tag", description="The tag to map to the PLC. Namespaces are separated by the tag namespace separator."),
            config.String("PLC Tag", description="The tag to map to the PLC"),
        )

        plc_elem = config.Object("PLC")
        plc_elem.add_elements(
            config.String("Name", default=None, description="The name of the PLC. This is used to identify the PLC in the Doover config."),
            config.String("Address", description="IP address or domain name of the PLC"),
            config.Integer("Port", default=44818, description="Port to connect on the PLC"),
            config.Boolean("Micro800", default=False, description="Whether the PLC is a Micro800"),
            config.String("Username", default=None, description="Username to connect to the PLC"),
            config.String("Password", default=None, description="Password to connect to the PLC"),
            config.Number("Sync Period", default=1.0, description="The period in seconds to sync the PLC"),
            config.Number("Timeout", default=0.2, description="The timeout in seconds to wait for a response from the PLC"),
            config.Array("Tag Mappings", element=plc_tag_mapping),
        )
        return plc_elem


def export():
    EnipCipInterfaceConfig().export(Path(__file__).parents[2] / "doover_config.json", "enip_cip_interface")

if __name__ == "__main__":
    export()
