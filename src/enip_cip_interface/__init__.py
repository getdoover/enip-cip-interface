from pydoover.docker import run_app

from .application import EnipCipInterfaceApplication
from .app_config import EnipCipInterfaceConfig

def main():
    """
    Run the application.
    """
    run_app(EnipCipInterfaceApplication(config=EnipCipInterfaceConfig()))
