
import logging
import time
from pylogix import PLC


# All tags from the EtherNet/IP server configuration
ALL_TAGS = [
    # Process variables
    "sim_generator.temperature",
    "sim_generator.pressure",
    "global_value",
    "global_status",
]

# ALL_TAGS = [
#     "Temperature",
#     "Pressure",
#     "Status",
#     "FlowRate",
# ]

def main() -> None:

    # Initialize PLC connection
    plc_host = '127.0.0.1'  # EtherNet/IP server address

    logging.info(f"Starting EtherNet/IP to Foxglove bridge")
    logging.info(f"Connecting to PLC at {plc_host}")
    logging.info(f"Streaming {len(ALL_TAGS)} tags to Foxglove")

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
                        result = comm.Read(tag_name)

                        if result.Status == "Success" and result.Value is not None:
                            print(f"Read {tag_name}: {result.Value}")

                        else:
                            logging.warning(f"Failed to read {tag_name}: {result.Status}")

                    except Exception as e:
                        logging.error(f"Error reading tag {tag_name}: {e}")

                time.sleep(0.1)
    except KeyboardInterrupt:
        logging.info("Shutting down bridge...")
    except Exception as e:
        logging.error(f"Bridge error: {e}")
    finally:
        logging.info("Bridge stopped")

if __name__ == "__main__":
    main()