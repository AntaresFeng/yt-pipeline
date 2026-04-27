import subprocess, time, signal

cmd = [r"python", "main.py"]
p = subprocess.Popen(
    cmd,
    cwd=r"C:/Users/admin/Project/yt-pipeline",
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
)
p.stdin.write("y\n")
p.stdin.flush()
time.sleep(5)
p.send_signal(signal.CTRL_BREAK_EVENT)
out, _ = p.communicate(timeout=30)
print(out)
print("child exit code:", p.returncode)
