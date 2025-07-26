import os
import logging
import time
import random
from pylogix import PLC

logging.basicConfig(level=logging.INFO)

# All tags from the EtherNet/IP server configuration
ALL_TAGS = [
    # Process variables
    "sim_generator.temperature",
    "sim_generator.pressure",
    "global_value",
    "global_status",
]

def main() -> None:

    # Get the PLC host from the environment variable if it exists
    plc_host = os.getenv("PLC_HOST", "127.0.0.1")

    logging.info(f"Connecting to PLC at {plc_host}")

    try:
        with PLC() as comm:
            comm.IPAddress = plc_host
            # comm.Micro800 = True

            while True:

                # all_tags = comm.GetTagList(allTags=True)
                # print(all_tags)

                # Read and stream all tags
                for tag_name in ALL_TAGS:
                    try:
                        # Read value from PLC
                        logging.info(f"Reading {tag_name}")
                        result = comm.Read(tag_name)

                        if result.Status == "Success" and result.Value is not None:
                            print(f"Read {tag_name}: {result.Value}")

                        else:
                            logging.warning(f"Failed to read {tag_name}: {result.Status}")

                    except Exception as e:
                        logging.error(f"Error reading tag {tag_name}: {e}")

                # Write a random value to the global_value tag
                logging.info(f"Writing to global_value: {random.random()}")
                comm.Write("global_value", random.random())

                time.sleep(5)
    except KeyboardInterrupt:
        logging.info("Shutting down bridge...")
    except Exception as e:
        logging.error(f"Bridge error: {e}")
    finally:
        logging.info("Bridge stopped")

if __name__ == "__main__":
    main()