"""Stand-ins for the pipeline, run in a spawned process by tests/test_webapp.py."""
import os, time


def sleepy(scan_id, paths, scans_dir):
    time.sleep(60)


def crashy(scan_id, paths, scans_dir):
    os._exit(3)                                   # as a crash in native code would end it
