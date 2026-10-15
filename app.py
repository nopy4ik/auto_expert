"""Локальный web-сервер без сторонних зависимостей. Запуск: python app.py."""
import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from rule_editor import ConflictError, RuleStore

ROOT = Path(__file__).resolve().parent
STORE = RuleStore(ROOT / 'data' / 'knowledge.json')


class Handler(BaseHTTPRequestHandler):
    def read_json(self, require_type=False):
        if require_type and self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
            raise ValueError('Требуется Content-Type: application/json')
        size = int(self.headers.get('Content-Length', '0'))
        if not 0 < size <= 65536:
            raise ValueError('Размер запроса недопустим')
        data = json.loads(self.rfile.read(size))
        if not isinstance(data, dict):
            raise ValueError('Ожидается объект JSON')
        return data

    def check_origin(self):
        origin = self.headers.get('Origin')
        expected = f'http://{self.headers.get("Host")}'
        if origin and (origin != expected or not self.headers.get('Host', '').startswith('127.0.0.1:')):
            raise ValueError('Редактирование разрешено только из локального приложения')

    @staticmethod
    def knowledge_response():
        system, revision = STORE.snapshot()
        return {'categories': system.kb['categories'], 'questions': system.kb['questions'],
                'rules': system.rules, 'rule_count': len(system.rules),
                'version': system.kb['version'], 'revision': revision}

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
            return self.send_json(self.knowledge_response())
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
        path = urlsplit(self.path).path
        if path == '/api/rules':
            return self.change_rule('create')
        if path != '/api/consult':
            return self.send_json({'error': 'Метод не найден'}, 404)
        try:
            data = self.read_json()
            system, _ = STORE.snapshot()
            result = system.consult(data.get('category'), data.get('answers', {}))
        except (ValueError, TypeError, KeyError, UnicodeDecodeError) as error:
            return self.send_json({'error': str(error)}, 400)
        self.send_json(result)

    def do_PUT(self):
        return self.change_rule('update')

    def do_DELETE(self):
        return self.change_rule('delete')

    def change_rule(self, action):
        path = urlsplit(self.path).path
        if action == 'create':
            if path != '/api/rules':
                return self.send_json({'error': 'Метод не найден'}, 404)
        elif not path.startswith('/api/rules/') or not path[len('/api/rules/'):].isdigit():
            return self.send_json({'error': 'Правило не найдено'}, 404)
        try:
            self.check_origin()
            data = self.read_json(require_type=True)
            rule = data.get('rule')
            rule_id = rule.get('id') if action == 'create' and isinstance(rule, dict) else int(path.rsplit('/', 1)[-1]) if action != 'create' else None
            if type(rule_id) is not int:
                raise ValueError('Номер правила должен быть целым числом')
            STORE.change(action, rule_id, rule, data.get('revision'))
        except ConflictError as error:
            return self.send_json({'error': str(error)}, 409)
        except (ValueError, TypeError, KeyError, UnicodeDecodeError) as error:
            return self.send_json({'error': str(error)}, 400)
        self.send_json(self.knowledge_response())


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
