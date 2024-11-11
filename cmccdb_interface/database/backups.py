import os
import subprocess

DATA_DIR = "/home/cmccdb-data"
BACKUP_DIR = DATA_DIR + "/uploads"
def commit_backup():
    cur_dir = os.getcwd()
    try:
        os.chdir(BACKUP_DIR)
        subprocess.call(
            ["git", "commit", "-a", "-m", "'new data upload'"]
        )
        subprocess.call(
            ["git", "push", "-a"]
        )
    finally:
        os.chdir(cur_dir)