import os


def proc_cpu(pid):
    """CPU seconds (user+system) of a process and its threads."""
    with open(f"/proc/{pid}/stat") as f:
        parts = f.read().rsplit(")", 1)[1].split()
    return (int(parts[11]) + int(parts[12])) / os.sysconf("SC_CLK_TCK")


def server_pid():
    return int(open("/home/user/bench/serve.pid").read())


def pg_cpu():
    """CPU seconds of all postgres processes (backends included)."""
    total = 0.0
    for pid in os.listdir("/proc"):
        if pid.isdigit():
            try:
                if open(f"/proc/{pid}/comm").read().strip() == "postgres":
                    total += proc_cpu(int(pid))
            except OSError:
                pass
    return total
