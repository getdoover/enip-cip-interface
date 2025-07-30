from pathlib import Path

from pydoover import config

class EnipCipInterfaceConfig(config.Schema):
    def __init__(self):
        self.port = config.Integer("Port", default=44818, description="The port to listen on for the ENIP server")
        self.tag_namespace_separator = config.String("Tag Namespace Separator", default="__", description="The separator to use between tag namespaces")

def export():
    EnipCipInterfaceConfig().export(Path(__file__).parents[2] / "doover_config.json", "enip_cip_interface")

if __name__ == "__main__":
    export()
