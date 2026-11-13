"""Provider protocol selection without importing the running app or making API calls."""
import ast
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch


class StructuredOutputTests(unittest.TestCase):
    def method(self):
        tree=ast.parse((Path(__file__).resolve().parents[1]/'agent_server/main.py').read_text())
        call=next(n for n in ast.walk(tree) if isinstance(n,ast.Call)
                  and isinstance(n.func,ast.Attribute) and n.func.attr=='with_structured_output')
        provider=SimpleNamespace(with_structured_output=lambda schema, **kwargs: kwargs.get('method','json_schema'))
        return eval(compile(ast.Expression(call),'<structured-output>','eval'),
                    {'os':os,'llm':provider,'QuerySpecBundle':object()})

    def test_default_is_function_calling_for_sonnet_compatible_route(self):
        with patch.dict(os.environ):
            os.environ.pop('LLM_STRUCTURED_METHOD',None)
            self.assertEqual(self.method(),'function_calling')

    def test_explicit_protocol_override_is_respected(self):
        with patch.dict(os.environ,{'LLM_STRUCTURED_METHOD':'json_schema'}):
            self.assertEqual(self.method(),'json_schema')

class _Message:
    def __init__(self,content):self.content=content
class _System(_Message):pass
class _Human(_Message):pass
class _Assistant(_Message):pass


class MessageOrderTests(unittest.TestCase):
    def prepare(self,messages):
        tree=ast.parse((Path(__file__).resolve().parents[1]/'agent_server/main.py').read_text())
        node=next((n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_prepare_structured_messages'),None)
        self.assertIsNotNone(node,'Structured messages must be normalized before provider calls')
        node.returns=None
        for arg in node.args.args:arg.annotation=None
        namespace={'SystemMessage':_System,'HumanMessage':_Human,'AIMessage':_Assistant}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),'<message-order>','exec'),namespace)
        return namespace['_prepare_structured_messages'](messages)

    def test_first_iteration_merges_system_instructions_before_user(self):
        user=_Human('Ищу программиста')
        result=self.prepare([_System('Правила'),user,_System('Итераций осталось: 2')])
        self.assertEqual([type(m) for m in result],[_System,_Human])
        self.assertEqual(result[0].content,'Правила\n\nИтераций осталось: 2')
        self.assertIs(result[1],user)

    def test_later_iteration_keeps_history_and_ends_with_user_request(self):
        user=_Human('Ищу программиста');previous=_Assistant('QuerySpec: {}');counts=_Assistant('Найден 1')
        result=self.prepare([_System('Правила'),user,previous,counts,_System('Итераций осталось: 1'),_System('Измени условия')])
        self.assertEqual([type(m) for m in result],[_System,_Human,_Assistant,_Assistant,_Human])
        self.assertEqual(result[1:4],[user,previous,counts])
        self.assertEqual(result[0].content,'Правила\n\nИтераций осталось: 1\n\nИзмени условия')

    def test_retry_does_not_append_another_user_if_already_last(self):
        user=_Human('Исходный запрос')
        result=self.prepare([_System('Правила'),user,_System('Верни валидный ответ')])
        self.assertEqual([type(m) for m in result],[_System,_Human])
        self.assertIs(result[-1],user)
