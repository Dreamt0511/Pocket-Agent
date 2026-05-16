#!/usr/bin/env python3
"""
Pocket-Agent 项目同步到手机脚本（全自动版本）
使用方法：
1. 先安装依赖：pip install paramiko
2. 直接运行：python sync_to_phone.py
无需手动输入密码，全程自动
"""

import os
import sys
import stat
from paramiko import SSHClient, AutoAddPolicy, SFTPClient

# 配置信息
SSH_CONFIG = {
    "host": "10.40.148.132",
    "port": 8022,
    "username": "u0_a391",
    "password": "0511",
    "remote_path": "/storage/emulated/0/手机agent开发/Pocket-Agent/",
    "backup_path": "/storage/emulated/0/手机agent开发/.env.backup"
}

# 需要同步的文件和目录（自动适配当前项目结构）
SYNC_ITEMS = [
    "agent/",
    "docs/",
    "main.py",
    "requirements.txt",
    "CLAUDE.md",
    "README.md",
    "termux指令.md"
]

# 需要排除的文件/目录
EXCLUDE_PATTERNS = [
    ".git",
    "__pycache__",
    ".pyc",
    ".env",
    ".log",
    "memory/",
    "node_modules",
    ".bat",
    "sync_",
    ".idea",
    ".vscode"
]


def is_excluded(path):
    """检查路径是否需要排除"""
    for pattern in EXCLUDE_PATTERNS:
        if pattern in path:
            return True
    return False


def sync_files(sftp, ssh, local_path, remote_base):
    """递归同步文件（使用SFTP）"""
    local_abspath = os.path.abspath(local_path)

    if os.path.isfile(local_abspath):
        # 单个文件
        if is_excluded(local_abspath):
            return
        remote_path = remote_base + os.path.basename(local_path)
        print(f"📤 同步文件: {local_path}")
        sftp.put(local_abspath, remote_path)
        return

    # 目录
    for root, dirs, files in os.walk(local_abspath):
        # 计算相对路径
        rel_path = os.path.relpath(root, os.path.dirname(local_abspath))
        remote_dir = remote_base + rel_path.replace("\\", "/") + "/"

        # 排除目录
        dirs[:] = [d for d in dirs if not is_excluded(os.path.join(root, d))]

        # 创建远程目录
        try:
            sftp.stat(remote_dir)
        except FileNotFoundError:
            # 目录不存在，逐级创建
            dir_parts = remote_dir.rstrip('/').split('/')
            current_path = ''
            for part in dir_parts:
                if not part:
                    current_path = '/'
                    continue
                current_path = os.path.join(current_path, part).replace('\\', '/')
                try:
                    sftp.stat(current_path)
                except FileNotFoundError:
                    sftp.mkdir(current_path)

        # 同步文件
        for file in files:
            local_file = os.path.join(root, file)
            if is_excluded(local_file):
                continue
            remote_file = remote_dir + file
            print(f"[同步] 同步文件: {os.path.join(rel_path, file)}")
            sftp.put(local_file, remote_file)


if __name__ == "__main__":
    print("=" * 50)
    print("Pocket-Agent 全自动同步工具")
    print("=" * 50)
    print(f"目标主机: {SSH_CONFIG['host']}:{SSH_CONFIG['port']}")
    print(f"远程路径: {SSH_CONFIG['remote_path']}")
    print(f"自动使用密码: {SSH_CONFIG['password']}")
    print("=" * 50)

    # 检查paramiko是否安装
    try:
        import paramiko
    except ImportError:
        print("❌ 缺少依赖，请先安装：")
        print("   pip install paramiko")
        input("\n按任意键退出")
        sys.exit(1)

    ssh = None
    sftp = None

    try:
        # 1. 连接SSH
        print("\n正在连接手机...")
        ssh = SSHClient()
        ssh.set_missing_host_key_policy(AutoAddPolicy())
        ssh.connect(
            hostname=SSH_CONFIG["host"],
            port=SSH_CONFIG["port"],
            username=SSH_CONFIG["username"],
            password=SSH_CONFIG["password"],
            timeout=10
        )
        print("SSH连接成功!")

        # 2. 备份配置文件
        print("\n💾 备份配置文件...")
        stdin, stdout, stderr = ssh.exec_command(
            f"cp -f {SSH_CONFIG['remote_path']}.env {SSH_CONFIG['backup_path']} 2>/dev/null"
        )
        stdout.channel.recv_exit_status()
        print("[完成] 配置文件已备份")

        # 3. 同步文件
        print("\n[信息] 开始同步文件...")
        sftp = ssh.open_sftp()

        for item in SYNC_ITEMS:
            if not os.path.exists(item):
                print(f"[警告] 跳过不存在的: {item}")
                continue
            sync_files(sftp, ssh, item, SSH_CONFIG["remote_path"])

        print("\n[完成] 文件同步完成!")

        # 4. 恢复配置文件
        print("\n[信息] 恢复配置文件...")
        stdin, stdout, stderr = ssh.exec_command(
            f"cp -f {SSH_CONFIG['backup_path']} {SSH_CONFIG['remote_path']}.env 2>/dev/null && rm -f {SSH_CONFIG['backup_path']}"
        )
        stdout.channel.recv_exit_status()
        print("[完成] 配置文件已恢复")

        # 5. 创建/更新同步记录文件
        from datetime import datetime
        sync_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sync_record_file = f"{SSH_CONFIG['remote_path']}最新同步记录.txt"

        # 构建同步记录内容
        sync_content = f"""同步时间: {sync_time}
同步主机: {SSH_CONFIG['host']}
同步目录: {os.getcwd()}
同步文件列表:
{chr(10).join(['- ' + item for item in SYNC_ITEMS if os.path.exists(item)])}
"""
        # 写入内容到远程文件（覆盖旧文件）
        stdin, stdout, stderr = ssh.exec_command(f"cat > {sync_record_file} << 'EOF'\n{sync_content}\nEOF")
        stdout.channel.recv_exit_status()
        print(f"[完成] 同步记录已更新: 最新同步记录.txt")

        # 完成
        print("\n" + "=" * 50)
        print("所有同步操作已完成!")
        print("=" * 50)
        print("现在可以在手机上运行项目测试了。")
        print(f"验证方式：查看手机项目根目录下的 最新同步记录.txt 文件，确认同步时间为 {sync_time}")

    except Exception as e:
        print(f"\n[错误] 同步失败: {str(e)}")
        print("\n请检查:")
        print("1. 手机和电脑是否在同一个WiFi下")
        print("2. 手机上的SSH服务是否已启动")
        print(f"3. IP地址是否正确: 当前配置是 {SSH_CONFIG['host']}")
    finally:
        if sftp:
            sftp.close()
        if ssh:
            ssh.close()

    input("\n按任意键退出")
