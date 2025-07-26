import time
import random
import sys
import logging
from typing import List, Any, Dict

from multiprocessing import Process

import cpppo
from cpppo.server.enip import device
from cpppo.server.enip.main import tags, main as enip_main

from pylogix import PLC

"""
Ethernet/IP Server For Doover
Based on cpppo server example:
https://github.com/pjkundert/cpppo/blob/master/server/enip/simulator_example.py


Seems like this needs to have two parts:
1. A cpppo server that runs in the background (cpppo)
2. A client that can be used to read and write new values to the server (pylogix)
"""

class EnipTag:
    def __init__(self, name: str, current_value: Any = None, default_value: str = None, tag_type: str = None, description: str = None, units: str = None, min_value: float = None, max_value: float = None):
        self.name = name
        self._tag_type = tag_type
        self._default_value = default_value or 0.0
        self._current_value = current_value
        self.description = description
        self.units = units
        self.min_value = min_value
        self.max_value = max_value

    def has_changed(self, compare: Any, exclude_values: bool = True):
        if not isinstance(compare, EnipTag):
            return False
        if self.name != compare.name:
            return True
        if self.tag_type != compare.tag_type:
            return True
        
        if exclude_values:
            return False
        
        if self.current_value != compare.current_value:
            return True
        if self.default_value != compare.default_value:
            return True
        
        return False

    @property
    def tag_type(self):
        return self.get_tag_type(self.current_value)

    @staticmethod
    def get_tag_type(value: Any):
        if isinstance(value, bool):
            return "BOOL"
        elif isinstance(value, float) or isinstance(value, int):
            return "REAL"
        if isinstance(value, list):
            inner_type = EnipTag.get_tag_type(value[0])
            return f"{inner_type}[{len(value)}]"
        else:
            return "STRING"

    @property
    def cppp0_arg(self):
        return f"{self.name}={self.tag_type}"

    @property
    def default_value(self):
        if self._default_value is None:
            return self._current_value
        return self._current_value
    
    @property
    def current_value(self):
        if self._current_value is None:
            return self._default_value
        return self._current_value
    
    @current_value.setter
    def current_value(self, value: Any):
        self._current_value = value

    def __str__(self):
        return f"{self.name} ({self.tag_type}) {self.current_value}"
    
    def __repr__(self):
        return f"{self.name} ({self.tag_type}) {self.current_value}"

class EnipServer:

    def __init__(self, tags: List[EnipTag], cpppo_log_level: int = logging.WARNING):
        self.tags: Dict[str, EnipTag] = {tag.name: tag for tag in tags}
        self._prev_tags = tags
        self._process = None
        self.cpppo_log_level = cpppo_log_level # Logging level for cpppo, it is very verbose
        self.open_client()
        self.start()

    def open_client(self, ip_address: str = "127.0.0.1", port: int = 44818):
        self._updater_client = PLC()
        self._updater_client.IPAddress = ip_address
        self._updater_client.Port = port

    def write_tags(self, values: Dict[str, Any]):
        for k, v in values.items():
            if k not in self.tags.keys():
                raise ValueError(f"Tag {k} not found")
            ## Update the current value for the tag
            self.tags[k].current_value = v
            ## Update the value in the client
            self._updater_client.Write(k, v)

    def set_tags(self, tags: List[EnipTag]):
        self.tags = {tag.name: tag for tag in tags}
        self.maybe_restart()

    def add_tag(self, tag: EnipTag):
        logging.info(f"Adding tag: {tag.name}")
        self.tags[tag.name] = tag
        self.maybe_restart()

    def have_tags_changed(self):
        result = False
        if len(self.tags) != len(self._prev_tags):
            result = True
        else:
            for k, v in self.tags.items():
                if k not in self._prev_tags:
                    result = True
                    break
                if v.has_changed(self._prev_tags[k]):
                    result = True
                    break
        self._prev_tags = self.tags.copy()
        return result
    
    def maybe_restart(self):
        if not self.have_tags_changed():
            return
        logging.warning("RESTARTING CPPPO SERVER FOR NEW TAGS")
        self.stop()
        self.start()

    def start(self):
        self._process = Process(target=self.main, args=(self.tags, self.cpppo_log_level))
        self._process.daemon = True
        self._process.start()

    def stop(self):
        if self._process is not None:
            self._process.terminate()
            self._process = None

    @staticmethod
    def main( tags_dict: Dict[str, EnipTag], cpppo_log_level: int = logging.WARNING, argv=None, idle_service=None, **kwargs ):
        """
        The main function for the cpppo server that is run in a separate process.
        More info here:
        https://github.com/pjkundert/cpppo/blob/master/server/enip/main.py
        """
        
        if argv is None:
            argv			= sys.argv[1:]

        ## For each tag, get add them to the argv
        for name, tag in tags_dict.items():
            argv.append(tag.cppp0_arg)

        # Configure logging for this process - Cpppo is very verbose, so we need to set the level to WARNING
        cpppo.log_cfg['level'] = cpppo_log_level
        logging.getLogger().setLevel(cpppo_log_level)

        # Create a custom attribute class that has access to the tags
        class TaggedAttribute(device.Attribute):
            def __init__(self, name, type_cls, default=0, error=0, mask=0):
                super().__init__(name, type_cls, default, error, mask)
                self.enip_tag = tags_dict.get(name)
                self.write_history = []

            def __setitem__(self, key, value):
                """Override to catch write operations"""
                if self.enip_tag:
                    # print(f"Caught write to {self.name}: {value}")
                    self.enip_tag.current_value = value
                    self.write_history.append(value)
                super().__setitem__(key, value)

            def __getitem__(self, key):
                """Override to catch read operations"""
                # if self.enip_tag:
                    # print(f"Caught read from {self.name}: {self.enip_tag.current_value}")
                return super().__getitem__(key)

        def idle_init():
            """Initialize the tags with their current values after the server starts"""
            if idle_init.complete:
                return
            idle_init.complete = True
            
            # Set initial values for all tags
            for name, tag in tags_dict.items():
                if name in tags_dict and hasattr(tags_dict[name], 'attribute'):
                    try:
                        tags_dict[name].attribute[0] = tag.current_value
                        print(f"Initialized {name} with value: {tag.current_value}")
                    except Exception as e:
                        print(f"Failed to initialize {name}: {e}")

        idle_init.complete = False

        return enip_main( argv=argv, attribute_class=TaggedAttribute, idle_service=idle_init, **kwargs )


if __name__ == "__main__":

    logging.basicConfig(level=logging.DEBUG)

    tags = [
        EnipTag("Temperature", "REAL[1]", 25.0),
        EnipTag("Pressure", "REAL[1]", 101.3),
        EnipTag("Status", "BOOL[1]", True),
        EnipTag("FlowRate", "REAL[1]", 10.0),
        EnipTag("Setpoint", "REAL[1]", 50.0),
        EnipTag("Alarm", "BOOL[1]", False),
    ]
    server = EnipServer(tags)

    extra_tags = [
        EnipTag("ExtraTag", "REAL[1]", 10.0),
    ]

    start_time = time.time()
    while True:
        time.sleep(1)

        ## Generate a random value for each tag
        values = {}
        for tag in tags:
            if tag.min_value is not None and tag.max_value is not None:
                values[tag.name] = random.uniform(tag.min_value, tag.max_value)
            else:
                values[tag.name] = random.random()
        logging.info(f"Writing values: {values}")
        server.write_tags(values)

        # After 20 seconds, add the extra tags
        if time.time() - start_time > 20:
            for t in extra_tags:
                server.add_tag(t)
            start_time = time.time()