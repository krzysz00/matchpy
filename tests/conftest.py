# -*- coding: utf-8 -*-
import pytest
from types import ModuleType

from matchpy.expressions.expressions import Wildcard, CommutativeOperation
from matchpy.matching.one_to_one import match as match_one_to_one
from matchpy.matching.many_to_one import ManyToOneMatcher
from matchpy.matching.syntactic import DiscriminationNet
from matchpy.expressions.functions import preorder_iter
from matchpy.matching.code_generation import CodeGenerator


def pytest_generate_tests(metafunc):
    if 'match' in metafunc.fixturenames:
        metafunc.parametrize('match', ['one-to-one', 'many-to-one', 'generated'], indirect=True)
    if 'match_syntactic' in metafunc.fixturenames:
        metafunc.parametrize('match_syntactic', ['one-to-one', 'many-to-one', 'syntactic', 'generated'], indirect=True)


def match_many_to_one(expression, pattern):
    try:
        commutative = next(
            p for p in preorder_iter(pattern.expression) if isinstance(p, CommutativeOperation)
        )
        next(wc for wc in preorder_iter(commutative) if isinstance(wc, Wildcard) and wc.min_count > 1)
    except StopIteration:
        pass
    else:
        pytest.xfail('Matcher does not support fixed wildcards with length != 1 in commutative operations')
    matcher = ManyToOneMatcher(pattern)
    for _, substitution in matcher.match(expression):
        yield substitution


GENERATED_TEMPLATE = '''
# -*- coding: utf-8 -*-
from matchpy import *
from tests.common import *

{}
'''.strip()


def match_generated(expression, pattern):
    try:
        next(
            p for p in preorder_iter(pattern.expression) if isinstance(p, CommutativeOperation)
        )
    except StopIteration:
        pass
    else:
        pytest.xfail('Code generation does not support commutativity yet.')
    if pattern.constraints:
        pytest.xfail('Code generation does not support constraints yet.')
    matcher = ManyToOneMatcher(pattern)
    generator = CodeGenerator(matcher)
    code = generator.generate_code()
    # code += '\nreturn match_root'
    code = GENERATED_TEMPLATE.format(code)
    compiled = compile(code, '', 'exec')
    module = ModuleType("generated_code")
    exec(compiled, module.__dict__)
    print(code)
    for _, substitution in module.match_root(expression):
        yield substitution



def syntactic_matcher(expression, pattern):
    matcher = DiscriminationNet()
    matcher.add(pattern)
    for _, substitution in matcher.match(expression):
        yield substitution


@pytest.fixture
def match(request):
    if request.param == 'one-to-one':
        return match_one_to_one
    elif request.param == 'many-to-one':
        return match_many_to_one
    elif request.param == 'generated':
        return match_generated
    else:
        raise ValueError("Invalid internal test config")


@pytest.fixture
def match_syntactic(request):
    if request.param == 'one-to-one':
        return match_one_to_one
    elif request.param == 'many-to-one':
        return match_many_to_one
    elif request.param == 'syntactic':
        return syntactic_matcher
    elif request.param == 'generated':
        return match_generated
    else:
        raise ValueError("Invalid internal test config")
