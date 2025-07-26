import logging
import time
import asyncio
from typing import Dict, Any

from pydoover.docker import Application

from .app_config import EnipCipInterfaceConfig
from .enip_server import EnipServer, EnipTag

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

    async def setup(self):
        """Initialize the EtherNet/IP server"""

        self.device_agent.add_subscription("tag_values", self.on_tag_update)
        ## Initialize the tags
        tag_contents = await self.device_agent.get_channel_aggregate_async("tag_values")
        if tag_contents is None or len(tag_contents) == 0:
            tag_contents = {"TEST": True}
        self.tags = self.generate_tags(tag_contents)
        logging.debug(f"Generated initial tags: {self.tags}")
        self.enip_server = EnipServer(tags=self.tags)
        self.on_tag_update("tag_values", tag_contents)

    async def main_loop(self):
        """Main application loop"""

        ## Every 10 seconds publish some analytics about the interactions
        logging.info("Available tags:")
        self.pretty_print_tags()

        channel_rate = self.get_loop_rate(self.channel_update_ts)
        logging.info(f"Channel update rate: {channel_rate:.2f} Hz")

        await asyncio.sleep(10)

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

    def generate_tags(self, value: Any, prefixes: list[str] = []):
        tags = []
        if isinstance(value, dict):
            for k, v in value.items():
                tags.extend(self.generate_tags(v, prefixes + [k]))
        else:
            tags.append(EnipTag(f"{'.'.join(prefixes)}", current_value=value))
        return tags

    def on_tag_update(self, channel_name: str, channel_values: Dict[str, Any]):
        logging.debug(f"Channel update from channel {channel_name}: {channel_values}")
        self.tags = self.generate_tags(channel_values)
        logging.debug(f"Generated tags: {self.tags}")
        self.enip_server.set_tags(self.tags)

        tag_values = {tag.name: tag.current_value for tag in self.tags}
        logging.debug(f"Writing tag values: {tag_values}")
        self.enip_server.write_tags(tag_values)

        self.channel_update_ts = self.log_ts(self.channel_update_ts)