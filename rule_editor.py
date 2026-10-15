"""Проверка и атомарное сохранение правил локальной базы знаний."""
import copy
import hashlib
import json
import os
import re
import tempfile
import threading
from pathlib import Path

from engine import ExpertSystem


class ConflictError(Exception):
    """Клиент редактирует устаревшую версию базы знаний."""


def _required_text(value, name):
    if not isinstance(value, str) or not value.strip() or len(value) > 1000:
        raise ValueError(f'Поле «{name}» должно содержать от 1 до 1000 символов')
    return value.strip()


def validate_rules(kb):
    """Проверяет редактируемые правила относительно вопросов и категорий."""
    categories = {c['id'] for c in kb['categories']}
    questions = {q['id']: q for q in kb['questions']}
    ids = set()
    producers = {}
    for rule in kb['rules']:
        if not isinstance(rule, dict) or type(rule.get('id')) is not int or rule['id'] < 1:
            raise ValueError('Номер правила должен быть положительным целым числом')
        if rule['id'] in ids:
            raise ValueError(f'Номер правила №{rule["id"]} уже занят')
        ids.add(rule['id'])
        if rule.get('category') not in categories:
            raise ValueError(f'Неизвестная категория у правила №{rule["id"]}')
        if rule.get('type') not in ('routing', 'terminal'):
            raise ValueError(f'Неверный тип правила №{rule["id"]}')
        rule['text'] = _required_text(rule.get('text'), 'Текст правила')
        then = rule.get('then')
        if not isinstance(then, dict):
            raise ValueError(f'Не задано следствие правила №{rule["id"]}')
        if rule['type'] == 'routing':
            if set(then) != {'fact'} or not isinstance(then['fact'], str) or not re.fullmatch(r'[a-z][a-z0-9_]*', then['fact']):
                raise ValueError('Промежуточному правилу нужен факт латиницей: буквы, цифры, _')
            fact = then['fact']
            if fact in questions or fact == 'complaint' or fact in producers:
                raise ValueError(f'Промежуточный факт «{fact}» уже используется')
            producers[fact] = rule
        else:
            if set(then) not in ({'conclusion', 'component'}, {'conclusion', 'component', 'kind'}):
                raise ValueError('Конечному правилу нужны вывод и узел автомобиля')
            then['conclusion'] = _required_text(then['conclusion'], 'Вывод')
            then['component'] = _required_text(then['component'], 'Узел автомобиля')
            if 'kind' in then and then['kind'] != 'normal_variant':
                raise ValueError('Недопустимый вид конечного вывода')

    def check_condition(condition, category):
        if not isinstance(condition, dict):
            raise ValueError('Условие должно быть объектом')
        if set(condition) == {'field', 'eq'}:
            field, expected = condition['field'], condition['eq']
            if not isinstance(field, str):
                raise ValueError('Неверное поле условия')
            if field == 'complaint':
                if expected != category:
                    raise ValueError('Условие жалобы должно совпадать с категорией правила')
            elif field in questions:
                question = questions[field]
                if question['category'] != category:
                    raise ValueError(f'Вопрос «{field}» относится к другой категории')
                if not any(type(expected) is type(o['value']) and expected == o['value'] for o in question['options']):
                    raise ValueError(f'Недопустимое значение для вопроса «{field}»')
            elif field in producers:
                if producers[field]['category'] != category or expected is not True:
                    raise ValueError(f'Некорректная ссылка на промежуточный факт «{field}»')
            else:
                raise ValueError(f'Неизвестный вопрос или факт «{field}»')
            return
        if len(condition) == 1 and ('all' in condition or 'any' in condition):
            items = condition.get('all', condition.get('any'))
            if not isinstance(items, list) or not items:
                raise ValueError('Группа условий не может быть пустой')
            for item in items:
                check_condition(item, category)
            return
        raise ValueError('Условие должно содержать field/eq либо группу all/any')

    for rule in kb['rules']:
        check_condition(rule.get('if'), rule['category'])
    # Дополнительно разворачивает ссылки и отклоняет циклы.
    ExpertSystem.from_data(kb)


class RuleStore:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.RLock()
        self._load()

    def _load(self):
        raw = self.path.read_bytes()
        self.system = ExpertSystem.from_data(json.loads(raw))
        self.revision = hashlib.sha256(raw).hexdigest()

    def snapshot(self):
        with self.lock:
            return self.system, self.revision

    def change(self, action, rule_id, rule, revision):
        with self.lock:
            if revision != self.revision or hashlib.sha256(self.path.read_bytes()).hexdigest() != self.revision:
                raise ConflictError('База знаний изменилась. Обновите страницу и повторите правку.')
            kb = copy.deepcopy(self.system.kb)
            rules = kb['rules']
            position = next((i for i, item in enumerate(rules) if item['id'] == rule_id), None)
            if action == 'create':
                if not isinstance(rule, dict):
                    raise ValueError('Ожидается объект правила')
                if position is not None:
                    raise ValueError(f'Правило №{rule_id} уже существует')
                rules.append(rule)
            elif action == 'update':
                if position is None:
                    raise ValueError(f'Правило №{rule_id} не найдено')
                if not isinstance(rule, dict) or rule.get('id') != rule_id:
                    raise ValueError('Нельзя менять номер правила при редактировании')
                rules[position] = rule
            elif action == 'delete':
                if position is None:
                    raise ValueError(f'Правило №{rule_id} не найдено')
                fact = rules[position]['then'].get('fact')
                if fact:
                    dependent = [item['id'] for item in rules if item['id'] != rule_id and fact in ExpertSystem.fields(item['if'])]
                    if dependent:
                        raise ValueError(f'Нельзя удалить правило №{rule_id}: от него зависят правила {", ".join(map(str, dependent))}')
                rules.pop(position)
            else:
                raise ValueError('Неизвестное действие')
            validate_rules(kb)
            payload = (json.dumps(kb, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
            temp_path = None
            try:
                with tempfile.NamedTemporaryFile(dir=self.path.parent, prefix='.knowledge-', suffix='.json', delete=False) as output:
                    temp_path = Path(output.name)
                    output.write(payload)
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(temp_path, self.path)
            finally:
                if temp_path is not None:
                    temp_path.unlink(missing_ok=True)
            self.system = ExpertSystem.from_data(kb)
            self.revision = hashlib.sha256(payload).hexdigest()
            return self.system, self.revision
