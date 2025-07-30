import asyncio
import logging
from typing import Any, Dict
import time

from enip_cip_interface.app_config import EnipTagSyncMode
from pylogix import PLC


class PlcSyncTask:

    def __init__(self, app, plc_config: Any):
        self.app = app
        self.plc_config = plc_config

        self._task = None

    @property
    def plc_name(self):
        name = self.plc_config.name.value or self.plc_config.address.value
        if name is None:
            raise ValueError("PLC name is not set")
        return str(name)

    async def start(self):
        if self._task is not None:
            raise RuntimeError("PLC sync task already running")
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _run(self):
        sync_period_secs = self.plc_config.sync_period.value

        logging.info(f"Starting PLC sync task for {self.plc_name}: {self.plc_config.address.value}:{self.plc_config.port.value}. With {len(self.plc_config.tag_mappings.elements)} tag mappings.")

        while True:
            try:
                with PLC() as comm:
                    comm.IPAddress = self.plc_config.address.value
                    comm.Port = self.plc_config.port.value
                    comm.Micro800 = self.plc_config.micro800.value
                    if self.plc_config.username.value is not None:
                        comm.UserTag = self.plc_config.username.value
                    if self.plc_config.password.value is not None:
                        comm.PasswordTag = self.plc_config.password.value

                    while True:
                        start_time = time.time()
                        await self._sync_from_plc(comm)
                        sleep_time = sync_period_secs - (time.time() - start_time) 
                        if sleep_time > 0:
                            await asyncio.sleep(sleep_time)

            except asyncio.CancelledError:
                logging.info(f"PLC sync task for {self.plc_name} cancelled")
                break
            except Exception as e:
                logging.exception(f"Error syncing PLC: {e}", exc_info=True)
                await asyncio.sleep(1)


    async def _sync_from_plc(self, comm: PLC):

        logging.debug(f"Syncing from PLC {self.plc_name}...")

        updates_to_publish: Dict[str, Any] = {}

        for tag_mapping in self.plc_config.tag_mappings.elements:
            if tag_mapping.mode.value == EnipTagSyncMode.FROM_PLC:
                result = comm.Read(tag_mapping.plc_tag.value)
                if result.Status == "Success" and result.Value is not None:
                    channel_msg = self.app.to_channel_message(tag_mapping.doover_tag.value, result.Value)
                    updates_to_publish.update(channel_msg)

            elif tag_mapping.mode.value == EnipTagSyncMode.TO_PLC:
                result = self.app.retreive_doover_tag_value(tag_mapping.doover_tag.value)
                if result is not None:
                    comm.Write(tag_mapping.plc_tag.value, result)

        logging.debug(f"Synced from PLC {self.plc_name}: {updates_to_publish}")
        if updates_to_publish:
            await self.app.device_agent.publish_to_channel_async(
                "tag_values",
                updates_to_publish,
                record_log=False,
                max_age=None,
            )