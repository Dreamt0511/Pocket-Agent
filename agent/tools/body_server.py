"""
Pocket Agent 3D - 身体控制服务器
可以作为独立程序运行，也可以作为模块导入
"""

import asyncio
import json
import os
import threading
import time
from http.server import HTTPServer, SimpleHTTPRequestHandler
from socketserver import ThreadingMixIn

# 命令队列
commands = []
command_id = 0
lock = threading.Lock()

# 浏览器消息队列（线程安全列表）
message_queue = []
msg_lock = threading.Lock()

# asyncio 事件（用于无轮询通知主循环）
_async_browser_event = None
_async_loop = None

def init_browser_event(loop):
    """初始化浏览器消息的 asyncio 事件（由 main.py 调用）"""
    global _async_browser_event, _async_loop
    _async_loop = loop
    _async_browser_event = asyncio.Event()

def get_browser_event():
    """获取浏览器消息 asyncio.Event，供 main.py await"""
    return _async_browser_event

def get_browser_message():
    """非阻塞获取浏览器消息，返回字符串或None"""
    with msg_lock:
        if message_queue:
            return message_queue.pop(0)
    return None

# AI回复事件队列（SSE）
response_events = []
response_event_id = 0
resp_lock = threading.Lock()

def push_response_event(event_type, data):
    """推送AI回复事件到浏览器SSE"""
    global response_event_id
    with resp_lock:
        response_event_id += 1
        response_events.append({
            'id': response_event_id,
            'type': event_type,
            **data
        })

class BodyControlHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, directory=None, **kwargs):
        # 设置静态文件目录为当前文件所在目录
        if directory is None:
            directory = os.path.dirname(os.path.abspath(__file__))
        super().__init__(*args, directory=directory, **kwargs)

    def do_GET(self):
        # 根路径重定向到body_viewer.html
        if self.path == '/' or self.path == '':
            self.send_response(302)
            self.send_header('Location', '/body_viewer.html')
            self.end_headers()
            return

        if self.path == '/api/events':
            # SSE: 服务器推送事件
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

            self.wfile.write(b'data: {"type":"connected"}\n\n')
            self.wfile.flush()

            last_id = 0
            try:
                while True:
                    with lock:
                        new_commands = [c for c in commands if c['id'] > last_id]

                    for cmd in new_commands:
                        last_id = cmd['id']
                        data = json.dumps(cmd)
                        self.wfile.write(f'data: {data}\n\n'.encode())
                        self.wfile.flush()

                    time.sleep(0.05)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        if self.path == '/api/status':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'status': 'ok', 'commands': len(commands)}).encode())
            return

        if self.path == '/api/response_stream':
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'keep-alive')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()

            self.wfile.write(b'data: {"type":"connected"}\n\n')
            self.wfile.flush()

            last_id = 0
            try:
                while True:
                    with resp_lock:
                        new_events = [e for e in response_events if e['id'] > last_id]

                    for evt in new_events:
                        last_id = evt['id']
                        data = json.dumps(evt, ensure_ascii=False)
                        self.wfile.write(f'data: {data}\n\n'.encode())
                        self.wfile.flush()

                    time.sleep(0.05)
            except (BrokenPipeError, ConnectionResetError):
                pass
            return

        super().do_GET()

    def do_POST(self):
        global command_id

        if self.path == '/api/set_bone':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)

            bone = data.get('bone')
            x = float(data.get('x', 0))
            y = float(data.get('y', 0))
            z = float(data.get('z', 0))

            with lock:
                command_id += 1
                cmd_id = command_id
                commands.append({
                    'id': cmd_id,
                    'type': 'set_bone',
                    'bone': bone,
                    'x': x,
                    'y': y,
                    'z': z
                })

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'ok': True, 'id': cmd_id}).encode())
            return

        elif self.path == '/api/set_position':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)

            x = float(data.get('x', 0))
            y = float(data.get('y', 0))
            z = float(data.get('z', 0))

            with lock:
                command_id += 1
                cmd_id = command_id
                commands.append({
                    'id': cmd_id,
                    'type': 'set_position',
                    'x': x,
                    'y': y,
                    'z': z
                })

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'ok': True, 'id': cmd_id}).encode())
            return

        elif self.path == '/api/idle':
            with lock:
                command_id += 1
                cmd_id = command_id
                commands.append({
                    'id': cmd_id,
                    'type': 'idle'
                })

            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'ok': True, 'id': cmd_id}).encode())
            return

        elif self.path == '/api/send_message':
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
            data = json.loads(body)
            text = data.get('text', '').strip()
            if text:
                with msg_lock:
                    message_queue.append(text)
                if _async_browser_event is not None and _async_loop is not None:
                    _async_loop.call_soon_threadsafe(_async_browser_event.set)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps({'ok': True, 'received': bool(text)}).encode())
            return

        self.send_response(404)
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def log_message(self, format, *args):
        """禁止日志输出到终端"""
        pass


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """支持多线程的HTTP服务器"""
    daemon_threads = True
    allow_reuse_address = True

def run_server_in_thread(port=18081):
    """在后台线程运行服务器"""
    server = ThreadedHTTPServer(('0.0.0.0', port), BodyControlHandler)
    server.serve_forever()


def run_server(port=18081):
    """运行服务器（阻塞）"""
    server = ThreadedHTTPServer(('0.0.0.0', port), BodyControlHandler)
    print(f'🚀 Body Control Server running on http://0.0.0.0:{port}')
    server.serve_forever()


if __name__ == '__main__':
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 18081
    run_server(port)
