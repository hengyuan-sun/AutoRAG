"""可选独立Worker：python -m raglab.worker。"""
import time

from .config import Settings
from .service import Lab


def main():
    lab = Lab(Settings())
    while True:
        if not lab.work_once():
            time.sleep(.5)


if __name__ == "__main__":
    main()
