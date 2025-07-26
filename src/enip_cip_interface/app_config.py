from pathlib import Path

from pydoover import config

class EnipCipInterfaceConfig(config.Schema):
    def __init__(self):
        self.port = config.Integer("Port", default=44818, description="The port to listen on for the ENIP server")

def export():
    EnipCipInterfaceConfig().export(Path(__file__).parents[2] / "doover_config.json", "enip_cip_interface")

if __name__ == "__main__":
    export()
