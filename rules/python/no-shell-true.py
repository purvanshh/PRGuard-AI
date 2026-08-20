# ruleid: no-shell-true
subprocess.run(command, shell=True)

# ruleid: no-shell-true
subprocess.Popen(cmd, shell=True)

# ruleid: no-shell-true
subprocess.call(user_cmd, shell=True)

# ok: no-shell-true
subprocess.run(command.split(), shell=False)

# ok: no-shell-true
subprocess.run(["ls", "-la"])