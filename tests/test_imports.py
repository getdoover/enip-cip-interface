"""
Basic tests for an application.

This ensures all modules are importable and that the config is valid.
"""

def test_import_app():
    from enip_cip_interface.application import EnipCipInterfaceApplication
    assert EnipCipInterfaceApplication

def test_config():
    from enip_cip_interface.app_config import EnipCipInterfaceConfig

    config = EnipCipInterfaceConfig()
    assert isinstance(config.to_dict(), dict)