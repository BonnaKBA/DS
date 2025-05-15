import os
import subprocess  # nosec B404
from datetime import datetime

log_dir = "logs/checker_log"
os.makedirs(log_dir, exist_ok=True)

timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

tools = [
    ("isort", ["isort", "."]),
    ("flake8", ["flake8", "."]),
    ("black", ["black", "."]),
    ("bandit", ["bandit", "-r", "."]),
]

for name, command in tools:
    log_path = os.path.join(log_dir, f"{name}_{timestamp}.log")
    print(f"[CHECKER] Running {name}...")
    with open(log_path, "w") as log_file:
        subprocess.run(
            command,
            stdout=log_file,
            stderr=log_file,
            shell=False,  # explicitly disable shell invocation
        )  # nosec B603

print(f"[DONE] Logs saved to {log_dir}/")
