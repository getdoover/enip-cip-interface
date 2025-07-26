import time
import random
import sys
import logging
import asyncio
import traceback
from typing import List, Any, Dict

from multiprocessing import Process, Manager, Event, Lock

import cpppo
from cpppo.server.enip import device
from cpppo.server.enip.main import tags, main as enip_main

"""
Ethernet/IP Server For Doover
Based on cpppo server example:
https://github.com/pjkundert/cpppo/blob/master/server/enip/simulator_example.py

This implementation uses:
1. A cpppo server that runs in a separate process (cpppo)
2. Shared memory for communication between the main process and the server process
3. External clients (like pylogix) can connect to read/write tags
"""

class EnipTag:
    def __init__(self, name: str, current_value: Any = None, default_value: str = None, tag_type: str = None):
        self.name = name
        self._tag_type = tag_type
        self._default_value = default_value or 0.0
        self._current_value = current_value

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

    def to_dict(self):
        return {
            "name": self.name,
            "current_value": self.current_value,
            "default_value": self.default_value,
            "tag_type": self.tag_type,
            "cpppo_arg": self.cppp0_arg,
        }

    def __str__(self):
        return f"{self.name} ({self.tag_type}) {self.current_value}"
    
    def __repr__(self):
        return f"{self.name} ({self.tag_type}) {self.current_value}"

class EnipReadOp:
    def __init__(self, tag: str, timestamp: float):
        self.tag_name: str = tag
        self.timestamp: float = timestamp

class EnipWriteOp:
    def __init__(self, tag: str, value: Any, timestamp: float):
        self.tag_name: str = tag
        self.value: Any = value
        self.timestamp: float = timestamp

class EnipServer:

    def __init__(self, port: int = 44818, tags: List[EnipTag] = None, cpppo_log_level: int = logging.WARNING):
        self.port = port

        self.tags: Dict[str, EnipTag] = {tag.name: tag for tag in tags}
        self._prev_tags = tags
        
        # Shared state for the cpppo server which is run in a separate process
        self._process_lock = Lock()
        self._process = None
        self._manager = Manager()
        self._shared_tags = self._manager.dict()
        self._read_operations = self._manager.list()
        self._write_operations = self._manager.list()
        self._write_received = self._manager.Event()
        
        self.cpppo_log_level = cpppo_log_level # Logging level for cpppo, it is very verbose
        # Remove pylogix client - we don't need it since we control the server directly
        with self._process_lock:
            self.start()

    # Remove the open_client method since we don't need the pylogix client

    def write_tags(self, values: Dict[str, Any]):
        """Update tag values directly in shared memory - no need for external client"""
        for k, v in values.items():
            if k not in self.tags.keys():
                raise ValueError(f"Tag {k} not found")
            ## Update the current value for the tag
            self.tags[k].current_value = v

        self._maybe_restart()
        # Sync the updated values to shared memory for the cpppo server
        self._sync_shared_tags()

    def set_tags(self, tags: List[EnipTag]):
        self.tags = {tag.name: tag for tag in tags}
        self._maybe_restart()

    def add_tag(self, tag: EnipTag):
        logging.info(f"Adding tag: {tag.name}")
        self.tags[tag.name] = tag
        self._maybe_restart()

    def pop_read_operations(self) -> List[EnipReadOp]:
        result = [EnipReadOp(**op) for op in self._read_operations]
        self._read_operations[:] = []  # Clear the list safely
        return result
    
    def pop_write_operations(self) -> List[EnipWriteOp]:
        result = [EnipWriteOp(**op) for op in self._write_operations]
        self._write_received.clear()
        self._write_operations[:] = []  # Clear the list safely
        return result
    
    async def await_write_received(self):
        while not self._write_received.is_set():
            await asyncio.sleep(0.2)

    def create_shared_memory(self):
        self._manager = Manager()
        self._shared_tags = self._manager.dict()
        self._read_operations = self._manager.list()
        self._write_operations = self._manager.list()
        self._write_received = self._manager.Event()

    def _is_shared_memory_valid(self):
        """Check if shared memory objects are still valid"""
        try:
            # Try to access the shared objects to see if they're still valid
            _ = len(self._shared_tags)
            _ = len(self._read_operations)
            _ = len(self._write_operations)
            return True
        except Exception:
            return False

    def _sync_shared_tags(self):
        if not self._is_shared_memory_valid():
            self.restart_server()

        for k, v in self.tags.items():
            self._shared_tags[k] = v.to_dict()

    def _have_tags_changed(self):
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
    
    def _maybe_restart(self):
        if not self._have_tags_changed():
            return
        self.restart_server()

    def restart_server(self):
        self.create_shared_memory()
        logging.warning("RESTARTING CPPPO SERVER FOR NEW TAGS")
        with self._process_lock:
            self.stop()
            self.start()

    def start(self):
        self._sync_shared_tags()
        self._process = Process(
            target=self.main,
            args=(
                self._shared_tags,
                self._read_operations,
                self._write_operations,
                self._write_received,
                self.port,
                self.cpppo_log_level
            )
        )
        self._process.daemon = True
        self._process.start()

    def stop(self):
        if self._process is not None:
            self._process.terminate()
            self._process = None

    @staticmethod
    def main(
            tags_dict: Dict[str, Any],
            read_operations: List[str],
            write_operations: List[str],
            write_received: Event,
            port: int = 44818,
            cpppo_log_level: int = logging.WARNING,
            argv=None,
            idle_service=None,
            **kwargs
        ):
        """
        The main function for the cpppo server that is run in a separate process.
        More info here:
        https://github.com/pjkundert/cpppo/blob/master/server/enip/main.py
        """
        
        if argv is None:
            argv = []
        
        argv.append(f"--address=0.0.0.0:{port}")

        ## For each tag, get add them to the argv
        for name, tag in tags_dict.items():
            argv.append(tag['cpppo_arg'])

        # Configure logging for this process - Cpppo is very verbose, so we need to set the level to WARNING
        cpppo.log_cfg['level'] = cpppo_log_level
        logging.getLogger().setLevel(cpppo_log_level)

        # Create a custom attribute class that has access to the tags
        class TaggedAttribute(device.Attribute):
            def __init__(self, name, type_cls, default=0, error=0, mask=0):
                super().__init__(name, type_cls, default, error, mask)

            @property
            def enip_tag(self):
                return tags_dict.get(self.name)

            @property
            def __current_value(self):
                if not self.enip_tag:
                    return None
                return self.enip_tag.get("current_value")

            def __setitem__(self, key, value):
                """Override to catch write operations"""
                try:
                    if isinstance(value, list):
                        value_to_write = value[0]
                    if self.enip_tag and value_to_write != self.__current_value:
                        self.enip_tag["current_value"] = value_to_write
                        write_operations.append({"tag": self.name, "value": value_to_write, "timestamp": time.time()})
                        write_received.set()
                except Exception as e:
                    print(f"Error setting item {key}: {e}")
                    traceback.print_exc()
                return super().__setitem__(key, value)

            def __getitem__(self, key):
                """Override to catch read operations"""
                try:
                    if self.enip_tag:
                        read_operations.append({"tag": self.name, "timestamp": time.time()})
                        return [self.__current_value]
                except Exception as e:
                    print(f"Error getting item {key}: {e}")
                    traceback.print_exc()
                result = super().__getitem__(key)
                return result

        def idle_init():
            """Initialize the tags with their current values after the server starts"""
            if idle_init.complete:
                return
            idle_init.complete = True

        idle_init.complete = False

        print(f"Starting cpppo server with args: {argv}")
        return enip_main( argv=argv, attribute_class=TaggedAttribute, idle_service=idle_init, **kwargs )


if __name__ == "__main__":

    logging.basicConfig(level=logging.DEBUG)

    tags = [
        EnipTag("Temperature", 25.0),
        EnipTag("Pressure", 101.3),
        EnipTag("Status", True),
        EnipTag("FlowRate", 10.0),
        EnipTag("Setpoint", 50.0),
        EnipTag("Alarm", False),
    ]
    server = EnipServer(port=44818, tags=tags)

    extra_tags = [
        EnipTag("ExtraTag", 10.0),
    ]

    start_time = time.time()
    while True:
        time.sleep(1)

        ## Generate a random value for each tag
        values = {}
        for tag in tags:
            values[tag.name] = random.random()
        logging.info(f"Updating values...")
        server.write_tags(values)

        # After 20 seconds, add the extra tags
        if time.time() - start_time > 10:
            for t in extra_tags:
                server.add_tag(t)

            # Only do this once
            extra_tags.clear()
            start_time = time.time()