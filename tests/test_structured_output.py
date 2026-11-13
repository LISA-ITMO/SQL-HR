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
