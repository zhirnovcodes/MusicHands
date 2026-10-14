import multiprocessing
import sys

from musichands_app.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
