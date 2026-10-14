"""Локальный web-сервер без сторонних зависимостей. Запуск: python app.py."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from engine import ExpertSystem

ROOT = Path(__file__).resolve().parent
SYSTEM = ExpertSystem()


class Handler(BaseHTTPRequestHandler):
    def send_json(self, data, status=200):
        payload = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/api/knowledge':
            return self.send_json({'categories': SYSTEM.kb['categories'], 'rules': SYSTEM.rules,
                                   'rule_count': len(SYSTEM.rules), 'version': SYSTEM.kb['version']})
        files = {'/': ('index.html', 'text/html'), '/style.css': ('style.css', 'text/css'),
                 '/app.js': ('app.js', 'text/javascript')}
        if path not in files:
            return self.send_json({'error': 'Страница не найдена'}, 404)
        name, mime = files[path]
        payload = (ROOT / 'static' / name).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mime + '; charset=utf-8')
        self.send_header('Content-Length', str(len(payload)))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        if urlsplit(self.path).path != '/api/consult':
            return self.send_json({'error': 'Метод не найден'}, 404)
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 65536:
                raise ValueError('Размер запроса недопустим')
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError('Ожидается объект JSON')
            result = SYSTEM.consult(data.get('category'), data.get('answers', {}))
        except (ValueError, TypeError, KeyError, UnicodeDecodeError) as error:
            return self.send_json({'error': str(error)}, 400)
        self.send_json(result)


def main():
    parser = argparse.ArgumentParser(description='Экспертная система диагностики автомобиля')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'Откройте http://127.0.0.1:{args.port} — остановка Ctrl+C', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
