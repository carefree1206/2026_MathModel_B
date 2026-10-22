"""Read-only display of original delivered HTML and CLI records; no robot action API."""
import json, threading
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
BASE=Path(__file__).resolve().parent.parent
ROOT=BASE.parent/'支撑材料'
OUT=BASE/'演示运行'
RUNS={8876:'run_20261005_174649_576453fe5969',8877:'run_20261005_174658_cf0598e842c8'}
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        identity=RUNS[self.server.server_port]
        if self.path in ('/','/问题三四_模拟终端界面.html'):
            body=(ROOT/'问题三四_模拟终端界面.html').read_text(encoding='utf-8').replace('__GUI_TOKEN__','read-only-replay').encode('utf-8')
            mime='text/html; charset=utf-8'
        elif self.path=='/api/catalog':
            body=json.dumps(dict(cases=[],active=identity,python='3.12.7 · CLI真实单局回放')).encode('utf-8');mime='application/json; charset=utf-8'
        elif self.path=='/api/run/'+identity:
            body=(OUT/identity/'trace.json').read_bytes();mime='application/json; charset=utf-8'
        elif self.path=='/favicon.ico':
            self.send_response(204);self.end_headers();return
        else:
            self.send_error(404);return
        self.send_response(200);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    def do_POST(self):
        self.send_error(405,'Read-only CLI replay; no robot actions are accepted')
    def log_message(self,*args):pass
servers=[ThreadingHTTPServer(('127.0.0.1',port),Handler) for port in RUNS]
for server in servers:
    threading.Thread(target=server.serve_forever,daemon=True).start()
print('Q3 http://127.0.0.1:8876 ; Q4 http://127.0.0.1:8877 ; read-only, no robot requests',flush=True)
try:threading.Event().wait()
except KeyboardInterrupt:
    for server in servers:server.shutdown();server.server_close()
