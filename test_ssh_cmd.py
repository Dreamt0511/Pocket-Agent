#!/usr/bin/env python3
"""SSH命令测试助手 - 通过SSH在手机上执行命令并返回结果"""
import sys
import json
from paramiko import SSHClient, AutoAddPolicy

SSH_CONFIG = {
    "hostname": "10.40.148.132",
    "port": 8022,
    "username": "u0_a391",
    "password": "0511",
}

def run_cmd(command, timeout=10):
    ssh = SSHClient()
    ssh.set_missing_host_key_policy(AutoAddPolicy())
    try:
        ssh.connect(**SSH_CONFIG, timeout=10)
        stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
        exit_code = stdout.channel.recv_exit_status()
        out = stdout.read().decode('utf-8', errors='replace').strip()
        err = stderr.read().decode('utf-8', errors='replace').strip()
        return exit_code, out, err
    except Exception as e:
        return -1, "", str(e)
    finally:
        ssh.close()

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if not cmd:
        print("Usage: python test_ssh_cmd.py '<command>'")
        sys.exit(1)

    print(f"$ {cmd}")
    print("-" * 50)
    code, out, err = run_cmd(cmd)
    if out:
        print(out)
    if err:
        print(f"[STDERR] {err}")
    print(f"[Exit: {code}]")
