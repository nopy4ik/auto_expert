"""Продукционный вывод и выбор следующего вопроса. Только стандартная библиотека."""
import json
from pathlib import Path

UNKNOWN = None


class ExpertSystem:
    def __init__(self, path=None):
        self._initialize(json.loads(Path(path or Path(__file__).parent / 'data/knowledge.json').read_text(encoding='utf-8')))

    @classmethod
    def from_data(cls, data):
        system = cls.__new__(cls)
        system._initialize(data)
        return system

    def _initialize(self, data):
        self.kb = data
        self.questions = {q['id']: q for q in self.kb['questions']}
        self.categories = {c['id']: c for c in self.kb['categories']}
        self.rules = self.kb['rules']
        self.producers = {r['then']['fact']: r for r in self.rules if 'fact' in r['then']}
        self._validate()

    def _validate(self):
        ids = [r['id'] for r in self.rules]
        if len(ids) != len(set(ids)):
            raise ValueError('Повторяющиеся номера правил')
        if len(self.questions) != len(self.kb['questions']):
            raise ValueError('Повторяющиеся вопросы')
        for rule in self.rules:
            if rule['category'] not in self.categories:
                raise ValueError('Неизвестная категория')
            self.expand(rule['if'])  # Проверяет ссылки и отсутствие циклов.

    def expand(self, condition, stack=()):
        """Заменяет промежуточный факт его условиями для выбора вопросов."""
        if 'all' in condition or 'any' in condition:
            op = 'all' if 'all' in condition else 'any'
            return {op: [self.expand(c, stack) for c in condition[op]]}
        field = condition['field']
        if field == 'complaint' or field in self.questions:
            return condition
        if field not in self.producers or field in stack or condition['eq'] is not True:
            raise ValueError(f'Некорректный промежуточный факт: {field}')
        return self.expand(self.producers[field]['if'], stack + (field,))

    @staticmethod
    def evaluate(condition, facts):
        """Трёхзначная логика: True, False, None (нет сведений)."""
        if 'all' in condition or 'any' in condition:
            op = 'all' if 'all' in condition else 'any'
            values = [ExpertSystem.evaluate(c, facts) for c in condition[op]]
            if op == 'all':
                return False if False in values else (None if None in values else True)
            return True if True in values else (None if None in values else False)
        value = facts.get(condition['field'])
        return None if value is None else value == condition['eq']

    @staticmethod
    def fields(condition):
        if 'field' in condition:
            return {condition['field']}
        op = 'all' if 'all' in condition else 'any'
        return set().union(*(ExpertSystem.fields(c) for c in condition[op]))

    def validate_answers(self, category, answers):
        if category not in self.categories or not isinstance(answers, dict):
            raise ValueError('Неизвестная жалоба или неверный формат ответов')
        for field, value in answers.items():
            q = self.questions.get(field)
            if q is None or q['category'] != category:
                raise ValueError(f'Вопрос не относится к выбранной жалобе: {field}')
            if value is None:
                continue
            options = [o['value'] for o in q['options']]
            if not any(type(value) is type(o) and value == o for o in options):
                raise ValueError(f'Недопустимый ответ: {field}')
        for constraint in self.kb.get('constraints', []):
            if self.evaluate(constraint['if'], answers) is True:
                raise ValueError(constraint['message'])

    def consult(self, category, answers):
        self.validate_answers(category, answers)
        facts = {'complaint': category, **answers}
        fired = []
        changed = True
        while changed:
            changed = False
            for rule in self.rules:
                if rule['category'] != category or rule['id'] in fired:
                    continue
                if self.evaluate(rule['if'], facts) is True:
                    fired.append(rule['id'])
                    if 'fact' in rule['then']:
                        facts[rule['then']['fact']] = True
                        changed = True

        terminals = [r for r in self.rules if r['category'] == category and 'conclusion' in r['then']]
        possible = [r for r in terminals if self.evaluate(self.expand(r['if']), facts) is not False]
        confirmed = [r for r in terminals if r['id'] in fired]
        relevant_fields = set().union(*(self.fields(self.expand(r['if'])) for r in possible)) if possible else set()
        available = []
        for q in self.kb['questions']:
            if q['category'] != category or q['id'] in answers or q['id'] not in relevant_fields:
                continue
            if q.get('gate') and self.evaluate(q['gate'], facts) is not True:
                continue
            available.append(q)
        # Приоритет задаёт понятный порядок дерева; частота в оставшихся
        # правилах разрешает равные приоритеты. Вероятности не вычисляются.
        available.sort(key=lambda q: (q['priority'], -sum(q['id'] in self.fields(self.expand(r['if'])) for r in possible)))
        question = available[0] if available else None
        pending = [r for r in possible if r['id'] not in fired]
        results = []
        for rule in confirmed:
            used = self.fields(self.expand(rule['if'])) - {'complaint'}
            results.append({
                'rule_id': rule['id'], 'text': rule['then']['conclusion'],
                'component': rule['then']['component'], 'kind': rule['then'].get('kind', 'hypothesis'),
                'rule_text': rule['text'],
                'evidence': [self.answer_record(k, answers[k]) for k in self.questions if k in used and k in answers],
                'trace': self.explain(rule, facts)
            })
        status = 'question' if question else ('matched' if results else ('insufficient' if pending else 'no_match'))
        return {
            'category': self.categories[category], 'status': status,
            'question': question, 'results': results, 'fired_rules': sorted(fired),
            'pending_rule_ids': [r['id'] for r in pending],
            'remaining_candidates': len(possible),
            'history': [self.answer_record(k, v) for k, v in answers.items()],
            'message': {
                'question': 'Ответьте на следующий вопрос.',
                'matched': 'Найдены возможные причины по введённым признакам.',
                'insufficient': 'Недостаточно данных для вывода по имеющимся правилам.',
                'no_match': 'В базе нет правила для указанного сочетания признаков.'
            }[status]
        }

    def explain(self, rule, facts):
        """Возвращает только фактически подтверждённые шаги вывода в порядке зависимостей."""
        steps = []
        seen = set()

        def add(key, item):
            if key not in seen:
                seen.add(key)
                steps.append(item)

        def visit(condition):
            if 'all' in condition:
                for part in condition['all']:
                    visit(part)
            elif 'any' in condition:
                for part in condition['any']:
                    if self.evaluate(part, facts) is True:
                        visit(part)
            else:
                field = condition['field']
                if field == 'complaint':
                    add(('complaint', field), {'type': 'complaint', 'text': self.categories[facts[field]]['title']})
                elif field in self.questions:
                    answer = self.answer_record(field, facts[field])
                    add(('answer', field), {'type': 'answer', 'question': answer['question'], 'answer': answer['answer']})
                else:
                    visit_rule(self.producers[field])

        def visit_rule(item):
            if ('rule', item['id']) in seen:
                return
            visit(item['if'])
            add(('rule', item['id']), {'type': 'rule', 'rule_id': item['id'], 'text': item['text']})

        visit_rule(rule)
        return steps

    def answer_record(self, field, value):
        q = self.questions[field]
        label = 'Не знаю' if value is None else next(o['label'] for o in q['options'] if type(o['value']) is type(value) and o['value'] == value)
        return {'id': field, 'question': q['text'], 'answer': label, 'value': value}
