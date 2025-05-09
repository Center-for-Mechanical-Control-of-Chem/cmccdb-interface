# import os
# import shlex
# import subprocess
# import flask

# BACKUP_DIR = "/app/cmccdb-data"
# def run_command(cmd, target_dir=None, raise_errors=True):
#     cwd = os.getcwd()
#     if isinstance(cmd, str):
#         cmd = shlex.split(cmd)
#     try:
#         if target_dir is not None:
#             os.chdir(BACKUP_DIR)
#         res = subprocess.run(
#             cmd,
#             capture_output=True
#         )
#     finally:
#         os.chdir(cwd)
    
#     if len(res.stderr) > 0:
#         if raise_errors:
#             raise OSError(shlex.join(cmd), res.stderr.decode("utf-8"))
#         else:
#             return {
#                 'stderr': res.stderr.decode("utf-8"),
#                 'stdout': res.stdout.decode("utf-8")
#             }
#     else:
#         return res.stdout.decode("utf-8")

# def listdir():
#     d = flask.request.args.get('d', '.')
#     return run_command(["ls", d]).split()

# def which():
#     e = flask.request.args.get('e', 'which')
#     return run_command(["which", e])

# def ssh_config():
#     config = run_command('ssh -G test@test.test', raise_errors=False)['stdout']
#     return f"<pre>{config}</pre>"

# def stat():
#     d = flask.request.args.get('d', '.')
#     data=run_command(["stat", d])
#     return f"<pre>{data}</pre>"