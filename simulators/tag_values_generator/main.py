import random
import time

from pydoover.docker import Application, run_app
from pydoover.config import Schema


class SampleSimulator(Application):
    def setup(self):
        pass

    def main_loop(self):
        self.set_tag("temperature", random.randint(1, 1000)/100)
        self.set_tag("pressure", random.randint(1, 1000))

        self.set_global_tag("global_value", random.randint(1, 100))
        self.set_global_tag("global_status", True)

        time.sleep(3)


def main():
    """Run the sample simulator application."""
    run_app(SampleSimulator(config=Schema()))

if __name__ == "__main__":
    main()
