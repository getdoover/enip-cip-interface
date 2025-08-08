import logging
import time
import asyncio
import multiprocessing
import traceback
from typing import Dict, Any, List

from pydoover.docker import Application

from .app_config import EnipCipInterfaceConfig
from .enip_server import EnipServer, EnipTag, EnipReadOp, EnipWriteOp
from .plc_sync import PlcSyncTask

log = logging.getLogger()

class EnipCipInterfaceApplication(Application):
    config: EnipCipInterfaceConfig  # not necessary, but helps your IDE provide autocomplete!

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.started: float = time.time()
        self.tags = []
        self.channel_update_ts = []
        self.enip_read_ts = []
        self.enip_write_ts = []
        self._max_ts = 30 # Max number of timestamps to keep track of

        self.enip_server = None
        self._write_task = None

        self._plc_sync_tasks: List[PlcSyncTask] = []

    async def setup(self):
        """Initialize the EtherNet/IP server"""
        
        # Set multiprocessing start method to spawn for better compatibility
        # Prevents warnings when using gRPC with multiprocessing (which is used to run the cpppo server)
        multiprocessing.set_start_method('spawn', force=True)

        ## Initialize the tags
        logging.debug("Adding subscription to tag_values")
        self.device_agent.add_subscription("tag_values", self.on_tag_update)
        tag_contents = await self.device_agent.get_channel_aggregate_async("tag_values")
        if tag_contents is None or len(tag_contents) == 0:
            logging.warning("No initial tag contents found, using default")
            tag_contents = {"TEST": True}
        self.tags = self.generate_tags(tag_contents)
        logging.info(f"Generated initial tags: {self.tags}")
        self.enip_server = EnipServer(port=self.config.port.value, tags=self.tags)

        self._write_task = asyncio.create_task(self.enip_write_task())

        for plc_config in self.config.plcs.elements:
            new_plc = PlcSyncTask(self, plc_config)
            await new_plc.start()
            self._plc_sync_tasks.append(new_plc)

        self.on_tag_update("tag_values", tag_contents)

    async def main_loop(self):
        """Main application loop"""

        ## Every 10 seconds publish some analytics about the interactions

        channel_rate = self.get_loop_rate(self.channel_update_ts)
        read_rate = self.get_loop_rate([op.timestamp for op in self.enip_server.pop_read_operations()])
        write_rate = self.get_loop_rate(self.enip_write_ts)
        logging.info(f"Channel update rate: {channel_rate:.2f} Hz")
        for plc_sync_task in self._plc_sync_tasks:
            logging.info(f"PLC Sync Task {plc_sync_task.plc_name} running at {plc_sync_task.sync_speed_hz:.2f} Hz: Average task time: {plc_sync_task.average_task_time:.2f} seconds")
        logging.info(f"ENIP Server Read rate: {read_rate:.2f} Hz")
        logging.info(f"ENIP Server Write rate: {write_rate:.2f} Hz")
        
        await asyncio.sleep(10)

    async def enip_write_task(self):
        logging.debug("Starting ENIP write task")
        while True:
            try:
                logging.debug("Waiting for ENIP write")
                await self.enip_server.await_write_received()
                writes = self.enip_server.pop_write_operations()
                logging.debug(f"Forwarding ENIP writes to channel: {writes}")
                for w in writes:
                    msg = self.to_channel_message(w.tag_name, w.value)
                    logging.debug(f"Publishing to channel: {msg}")
                    await self.device_agent.publish_to_channel_async(
                        "tag_values",
                        msg,
                        record_log=False,
                        max_age=None,
                    )
                    self.enip_write_ts = self.log_ts(self.enip_write_ts)
            except asyncio.CancelledError:
                logging.debug("ENIP write task cancelled")
                break
            except Exception as e:
                logging.error(f"Error forwarding ENIP writes to channel: {e}")
                traceback.print_exc()
                await asyncio.sleep(1)

    def log_ts(self, records: list[float]):
        ## Do some logging
        records.append(time.time())
        if len(records) > self._max_ts:
            records.pop(0)
        return records
    
    def get_loop_rate(self, records: list[float]):
        if len(records) > 1:
            first_ts = records[0]
            dt = records[-1] - first_ts
            rate = len(records) / dt
            return rate
        return 0.0

    def pretty_print_tags(self):
        for tag in self.enip_server.tags.values():
            logging.info(f"{tag.name}: {tag.tag_type} {tag.current_value}")

    def on_tag_update(self, channel_name: str, channel_values: Dict[str, Any]):
        if self.enip_server is None:
            logging.warning("ENIP server not initialized, skipping tag update")
            return
        logging.debug(f"Channel update from channel {channel_name}: {channel_values}")
        self.tags = self.generate_tags(channel_values)
        logging.debug(f"Generated tags: {self.tags}")
        self.enip_server.set_tags(self.tags)

        tag_values = {tag.name: tag.current_value for tag in self.tags}
        logging.debug(f"Writing tag values: {tag_values}")
        self.enip_server.write_tags(tag_values)

        self.channel_update_ts = self.log_ts(self.channel_update_ts)

    def generate_tags(self, value: Any, prefixes: list[str] = []):
        tags = []
        if isinstance(value, dict):
            for k, v in value.items():
                tags.extend(self.generate_tags(v, prefixes + [k]))
        else:
            delimiter = self.config.tag_namespace_separator.value
            tags.append(EnipTag(f"{delimiter.join(prefixes)}", current_value=value))
        return tags

    def to_channel_message(self, enip_tag_name: str, enip_tag_value: Any):
        delimiter = self.config.tag_namespace_separator.value
        s = enip_tag_name.split(delimiter)
        if len(s) == 1:
            res = {
                enip_tag_name: enip_tag_value
            }
            return res
        # Compose a nested dictionary for as many more elements as there are
        result = {}
        for i in range(0, len(s)-1):
            result[s[i]] = {
                s[i+1]: enip_tag_value
            }
        return result
    
    def retreive_doover_tag_value(self, delimited_tag_name: str):
        try:
            delimiter = self.config.tag_namespace_separator.value
            s = delimited_tag_name.split(delimiter)
            if len(s) < 1:
                raise ValueError(f"Invalid tag name: {delimited_tag_name}")
            if len(s) == 1:
                return self.get_global_tag(s[0])
            if len(s) >= 2:
                result = self.get_tag(s[1], app_key=s[0])
                for i in range(2, len(s)):
                    if isinstance(result, dict):
                        result = result[s[i]]
                    else:
                        raise ValueError(f"Tag {delimited_tag_name} not found")
            return result
        except Exception as e:
            logging.exception(f"Error retrieving tag value: {e}", exc_info=True)
            return None
