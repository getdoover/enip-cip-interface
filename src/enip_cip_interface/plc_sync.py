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
        self.last_read_values = {}
        self.last_tag_value = {}
        self.dda_changes = []
        self.enip_changes = []

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
                    try:
                        comm.UserTag = self.plc_config.username.value
                        comm.PasswordTag = self.plc_config.password.value
                    except Exception as e:
                        logging.warning(f"Failed to set UserTag/PasswordTag for {self.plc_name}: {e}")

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

        updates = []

        for tag_mapping in self.plc_config.tag_mappings.elements:
            if tag_mapping.mode.value == EnipTagSyncMode.FROM_PLC:
                result = comm.Read(tag_mapping.plc_tag.value)
                tag_value = self.app.retreive_doover_tag_value(tag_mapping.doover_tag.value)
                print("retrieving tag value:", tag_value, "from tag:", tag_mapping.doover_tag.value)
                print(result.TagName, result.Value, result.Status)
                if result.Status == "Success" and result.Value is not None:
                    last_tag_val = self.last_tag_value.get(tag_mapping.plc_tag.value, None)
                    last_plc_read_val = self.last_read_values.get(tag_mapping.plc_tag.value, None)
                    tag_name = tag_mapping.plc_tag.value
                        
                    if tag_value is not None and last_plc_read_val is not None and last_tag_val is not None:
                        
                        self.dda_changes = []
                        self.enip_changes = []

                        # Check for new changes iff the their are not current changes
                        if tag_name not in self.dda_changes and tag_name not in self.enip_changes:
                            # enip change - change from PLC
                            if round(tag_value, 3)==round(last_tag_val)==round(last_plc_read_val)!=round(result.Value):
                                self.enip_changes.append(tag_name)
                            # DDA Change - change from App code or Doover user
                            elif round(last_plc_read_val)==round(result.Value)==round(last_tag_val)!=round(tag_value, 3):
                                self.dda_changes.append(tag_name)
                        
                        else: #there is a change active
                            #check the all values are equal - change successful
                            if round(tag_value, 3)==round(last_tag_val)==round(last_plc_read_val)==round(result.Value):
                                #if state settles remove tag name from change lists
                                if tag_name in self.dda_changes:
                                    self.dda_changes.remove(tag_name)
                                    # print(f"Removed from DDA changes: {tag_name}")
                                if tag_name in self.enip_changes:
                                    self.enip_changes.remove(tag_name)
                            
                            # Change is active but not successful       
                            elif tag_name in self.dda_changes:
                                # there has been a dda change, write to PLC:
                                print("active DDA change, writing to PLC")
                                t = comm.Write(tag_mapping.plc_tag.value, tag_value)
                                print("Active DDA Change, writing: ", t.TagName, t.Value, "Success: ", t.Status)

                            elif tag_name in self.enip_changes:
                                # there has been an enip change, write to DDA:
                                print("active enip change, writing to Doover tag")
                                print(f"Publishing to channel: {tag_mapping.doover_tag.value} -> {result.Value}")
                                channel_msg = self.app.to_channel_message(tag_mapping.doover_tag.value, result.Value)
                                updates.append(channel_msg)
                        
                        # if round(result.Value,3)!=last_plc_read_val and tag_mapping.plc_tag.value not in self.last_writes:
                        #     self.last_writes.append(tag_mapping.plc_tag.value)
            
                        # if round(last_plc_read_val,3) == round(result.Value,3) and round(tag_value,3) != round(last_dda_cmd,3) and tag_mapping.plc_tag.value not in self.last_writes:
                        #     print(f"A PLC read value was updated from the Doovit, writing to PLC {tag_mapping.plc_tag.value}: {tag_value}")
                        #     t = comm.Write(tag_mapping.plc_tag.value, tag_value)
                        #     # print(f"Writing to PLC {tag_mapping.plc_tag.value}: {result}")
                        #     continue
                        
                        # if (tag_value == last_dda_cmd == result.Value == last_plc_read_val):
                        #     if tag_mapping.plc_tag.value in self.last_writes:
                        #         self.last_writes.remove(tag_mapping.plc_tag.value)
                        #         print('successfully removed from last_writes')
                        #     continue
                        
                        # if tag_name in self.
                            
                            # print(f"Skipping write to PLC {tag_mapping.plc_tag.value} as value is unchanged: {result.Value}")
                            # continue

                    # print(f"Publishing to channel: {tag_mapping.doover_tag.value} -> {result.Value}")
                    channel_msg = self.app.to_channel_message(tag_mapping.doover_tag.value, result.Value)
                    updates.append(channel_msg)
                    # print(f"Publishing to channel: {tag_mapping.doover_tag.value} -> {result.Value}")
                    # channel_msg = self.app.to_channel_message(tag_mapping.doover_tag.value, result.Value)
                    # updates.append(channel_msg)
                    # if round(result.Value,3)!=last_plc_read_val:
                    #     self.last_writes.append(tag_mapping.plc_tag.value)
                        
                    self.last_read_values[tag_mapping.plc_tag.value] = result.Value
                    self.last_tag_value[tag_mapping.plc_tag.value] = tag_value

            elif tag_mapping.mode.value == EnipTagSyncMode.TO_PLC:
                result = self.app.retreive_doover_tag_value(tag_mapping.doover_tag.value)
                print(f"Writing to PLC {tag_mapping.plc_tag.value}: {result}")
                if result is not None:
                    t = comm.Write(tag_mapping.plc_tag.value, result)
                    print(t.TagName, t.Value, t.Status)

        for update in updates:
            key = next(iter(update))
            if key in updates_to_publish:
                updates_to_publish[key].update(update[key])
            else:
                updates_to_publish[key] = update[key]

        print(f"Synced from PLC {self.plc_name}: {updates_to_publish}")
        if updates_to_publish:
            await self.app.device_agent.publish_to_channel_async(
                "tag_values",
                updates_to_publish,
                record_log=False,
                max_age=None,
            )