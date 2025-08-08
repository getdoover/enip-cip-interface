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
        self.task_run_times = {} # A dict of the timestamp and the time in seconds the task took to run

        self.last_sync_agreed_values = {}

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

    @property
    def average_task_time(self):
        if not self.task_run_times:
            return 0
        return sum(self.task_run_times.values()) / len(self.task_run_times)

    @property
    def sync_speed_hz(self):
        if not self.task_run_times:
            return 0
        timestamps = list(self.task_run_times.keys())
        timestamps.sort()
        return len(timestamps) / (timestamps[-1] - timestamps[0])

    async def _run(self):
        sync_period_secs = self.plc_config.sync_period.value

        logging.info(f"Starting PLC sync task for {self.plc_name}: {self.plc_config.address.value}:{self.plc_config.port.value}. With {len(self.plc_config.tag_mappings.elements)} tag mappings.")

        while True:
            try:
                with PLC() as comm:
                    comm.IPAddress = self.plc_config.address.value
                    comm.Port = self.plc_config.port.value
                    comm.Micro800 = self.plc_config.micro800.value
                    comm.SocketTimeout = self.plc_config.timeout.value
                    try:
                        comm.UserTag = self.plc_config.username.value
                        comm.PasswordTag = self.plc_config.password.value
                    except Exception as e:
                        logging.warning(f"Failed to set UserTag/PasswordTag for {self.plc_name}: {e}")

                    while True:
                        start_time = time.time()
                        await self._sync_from_plc(comm)

                        ## Record some analytics about the task run time
                        self.task_run_times[start_time] = time.time() - start_time
                        while len(self.task_run_times) > 10:
                            self.task_run_times.pop(min(self.task_run_times.keys()))

                        sleep_time = sync_period_secs - (time.time() - start_time) 
                        if sleep_time > 0:
                            await asyncio.sleep(sleep_time)

            except asyncio.CancelledError:
                logging.info(f"PLC sync task for {self.plc_name} cancelled")
                break
            except Exception as e:
                logging.exception(f"Error syncing PLC: {e}", exc_info=True)
                await asyncio.sleep(1)

    ## Sync Helpers
    def get_sync_values(self, tag_mapping: Any, comm: PLC):
        plc_response = comm.Read(tag_mapping.plc_tag.value)
        if plc_response.Status == "Success":
            plc_value = plc_response.Value
        else:
            logging.warning(f"Failed to read PLC tag {tag_mapping.plc_tag.value}: {plc_response.Status}")
            plc_value = None
        doover_value = self.app.retreive_doover_tag_value(tag_mapping.doover_tag.value)
        last_agreed = self.last_sync_agreed_values.get(tag_mapping.plc_tag.value, None)
        return plc_value, doover_value, last_agreed
    
    def propogate_to_plc(self, tag_mapping: Any, tag_value: Any, comm: PLC):
        comm.Write(tag_mapping.plc_tag.value, tag_value)
        self.last_sync_agreed_values[tag_mapping.plc_tag.value] = tag_value
    
    def propogate_to_doover(self, tag_mapping: Any, tag_value: Any):
        self.last_sync_agreed_values[tag_mapping.plc_tag.value] = tag_value
        channel_msg = self.app.to_channel_message(tag_mapping.doover_tag.value, tag_value)
        return channel_msg

    def has_changed(self, value1: Any, value2: Any, float_tolerance: float = 0.01):
        if isinstance(value1, float) and isinstance(value2, float):
            return abs(value1 - value2) > float_tolerance
        return value1 != value2


    ## Main Sync Function
    async def _sync_from_plc(self, comm: PLC):
        logging.debug(f"Syncing from PLC {self.plc_name}...")

        updates = []

        for tag_mapping in self.plc_config.tag_mappings.elements:

            if tag_mapping.mode.value == EnipTagSyncMode.SYNC_PLC_PREFERRED:
                plc_value, doover_value, last_agreed = self.get_sync_values(tag_mapping, comm)
                if plc_value is not None:
                    if last_agreed is None or self.has_changed(last_agreed, plc_value):
                        updates.append(self.propogate_to_doover(tag_mapping, plc_value))
                    elif self.has_changed(last_agreed, doover_value):
                        self.propogate_to_plc(tag_mapping, doover_value, comm)

            elif tag_mapping.mode.value == EnipTagSyncMode.SYNC_DOOVER_PREFERRED:
                plc_value, doover_value, last_agreed = self.get_sync_values(tag_mapping, comm)
                if plc_value is not None:
                    if last_agreed is None or self.has_changed(last_agreed, doover_value):
                        self.propogate_to_plc(tag_mapping, doover_value, comm)
                    elif self.has_changed(last_agreed, plc_value):
                        updates.append(self.propogate_to_doover(tag_mapping, plc_value))

            elif tag_mapping.mode.value == EnipTagSyncMode.FROM_PLC:
                result = comm.Read(tag_mapping.plc_tag.value)
                if result.Status == "Success" and result.Value is not None:
                    channel_msg = self.app.to_channel_message(tag_mapping.doover_tag.value, result.Value)
                    updates.append(channel_msg)

            elif tag_mapping.mode.value == EnipTagSyncMode.TO_PLC:
                result = self.app.retreive_doover_tag_value(tag_mapping.doover_tag.value)
                if result is not None:
                    t = comm.Write(tag_mapping.plc_tag.value, result)


        updates_to_publish: Dict[str, Any] = {}

        for update in updates:
            key = next(iter(update))
            if key in updates_to_publish:
                updates_to_publish[key].update(update[key])
            else:
                updates_to_publish[key] = update[key]

        logging.debug(f"Synced from PLC {self.plc_name}: {updates_to_publish}")
        if updates_to_publish:
            await self.app.device_agent.publish_to_channel_async(
                "tag_values",
                updates_to_publish,
                record_log=False,
                max_age=None,
            )