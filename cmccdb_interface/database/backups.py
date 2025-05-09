import os
import subprocess
import shlex

def run_command(cmd, target_dir=None, raise_errors=True):
    cwd = os.getcwd()
    if isinstance(cmd, str):
        cmd = shlex.split(cmd)
    try:
        if target_dir is not None:
            os.chdir(target_dir)
        res = subprocess.run(
            cmd,
            capture_output=True
        )
    finally:
        os.chdir(cwd)
    
    if len(res.stderr) > 0:
        if raise_errors:
            raise OSError(shlex.join(cmd), res.stderr.decode("utf-8"))
        else:
            return {
                'stderr': res.stderr.decode("utf-8"),
                'stdout': res.stdout.decode("utf-8")
            }
    else:
        return res.stdout.decode("utf-8")

BACKUP_DIR = "/app/cmccdb-data"
def run_git(args):
    if isinstance(args, str):
        args = shlex.split(args)
    cmd = ["git", *args]
    return run_command(cmd, target_dir=BACKUP_DIR)

class GIT_ENABLED:
    flag = False
def enable_git():
    if not GIT_ENABLED.flag:
        GIT_ENABLED.flag = True
        return {
            "git":run_git(f"config --global --add safe.directory {BACKUP_DIR}"),
            "keygen":run_command("bash /root/.ssh/configure_agent")
        }

def git_info():
    return {
        'username': run_git("config user.name"),
        'email': run_git("config user.email"),
        'remote': run_git("remote get-url origin")
    }

def git_backup():
    try:
        enable_git()
    except OSError:
        pass
    add_message = run_git("add -A")
    commit_message = run_git("commit -a -m 'uploads'")
    push_message = run_git("push")
    return {
        "add": add_message,
        "commit": commit_message,
        "push": push_message
    }