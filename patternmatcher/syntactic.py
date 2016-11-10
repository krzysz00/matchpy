# -*- coding: utf-8 -*-
from reprlib import recursive_repr
from typing import (Any, Dict, FrozenSet, Generic, Iterator, List, Optional,
                    Set, Tuple, Type, TypeVar, Union)

from graphviz import Digraph

from patternmatcher.expressions import (Arity, Expression, Operation, Symbol,
                                        SymbolWildcard, Variable, Wildcard,
                                        freeze)

T = TypeVar('T')


class _OperationEnd(object):
    """Represents the end of an operation expression in a :class:`FlatTerm`.

    Used for :const:`OPERATION_END` as a singleton. Could also be a plain object,
    but the string representation is customized.
    """

    def __str__(self):
        return ')'

    __repr__ = __str__

OPERATION_END = _OperationEnd()
"""Constant used to represent the end of an operation in a :class:`FlatTerm`.

This is a singleton object that has *)* as representation.
Is is also used by the :class:`DiscriminationNet`.
"""


class _Epsilon(object):
    """Represents an epsilon transition label for the :class:`DiscriminationNet`.

    Used for :const:`EPSILON` as a singleton. Could also be a plain object,
    but the string representation is customized.
    """

    def __str__(self):
        return 'ε'

    __repr__ = __str__

EPSILON = _Epsilon()
"""Constant used to label an epsilon transition for the :class:`DiscriminationNet`.

This is a singleton object that has *ε* as representation.
"""


def is_operation(term: Any) -> bool:
    """Return True iff the given term is a subclass of :class:`.Operation`."""
    return isinstance(term, type) and issubclass(term, Operation)


def is_symbol_wildcard(term: Any) -> bool:
    """Return True iff the given term is a subclass of :class:`.Symbol`."""
    return isinstance(term, type) and issubclass(term, Symbol)


def _get_symbol_wildcard_label(state: '_State', symbol: Symbol) -> Type[Symbol]:
    """Return the transition target for the given symbol type from the the given state or None if it does not exist."""
    return next((t for t in state.keys() if is_symbol_wildcard(t) and isinstance(symbol, t)), None)

# Broken without latest version of the typing package
# TermAtom = Union[Symbol, Type[Operation], Type[Symbol], _OperationEnd]
# So for now use the non-generic version
TermAtom = Union[Symbol, Wildcard, type, _OperationEnd]
# TransitionLabel = Union[Symbol, Type[Operation], Type[Symbol], Type[Wildcard], _OperationEnd, _Epsilon]
TransitionLabel = Union[Symbol, type, _OperationEnd, _Epsilon]

class FlatTerm(List[TermAtom]):
    """A flattened representation of an :class:`.Expression`.

    This is a subclass of list. This representation is similar to the prefix notation generated by
    :meth:`.Expression.preorder_iter`, but contains some additional elements.

    Operation expressions are represented by the :func:`type` of the operation before the operands as well as
    :const:`OPERATION_END` after the last operand of the operation:

    >>> FlatTerm(f(a, b))
    [f, a, b, )]

    Variables are not included in the flatterm representation, only wildcards remain.

    >>> FlatTerm(x_)
    [_]

    Consecutive wildcards are merged, as the :class:`DiscriminationNet` cannot handle multiple consecutive sequence
    wildcards:

    >>> FlatTerm(f(_, _))
    [f, _[2], )]
    >>> FlatTerm(f(_, __, __))
    [f, _[3+], )]

    Furthermore, every :class:`SymbolWildcard` is replaced by its :attr:`~SymbolWildcard.symbol_type`:

    >>> class SpecialSymbol(Symbol):
    ...     pass
    >>> FlatTerm(Wildcard.symbol(SpecialSymbol)) == [SpecialSymbol]
    True

    Symbol wildcards are also not merged like regular wildcards, because they can never be sequence wildcards.
    """

    def __init__(self, expression: Expression) -> None:
        super().__init__(FlatTerm._combined_wildcards_iter(FlatTerm._flatterm_iter(expression)))

    @staticmethod
    def _flatterm_iter(expression: Expression) -> Iterator[TermAtom]:
        """Generator that yields the atoms of the expressions in prefix notation with operation end markers."""
        if isinstance(expression, Variable):
            yield from FlatTerm._flatterm_iter(expression.expression)
        elif isinstance(expression, Operation):
            yield type(expression)
            for operand in expression.operands:
                yield from FlatTerm._flatterm_iter(operand)
            yield OPERATION_END
        elif isinstance(expression, SymbolWildcard):
            yield expression.symbol_type
        elif isinstance(expression, (Symbol, Wildcard)):
            yield expression
        else:
            raise TypeError()

    @staticmethod
    def _combined_wildcards_iter(flatterm: Iterator[TermAtom]) -> Iterator[TermAtom]:
        """Combine consecutive wildcards in a flatterm into a single one."""
        last_wildcard = None  # type: Optional[Wildcard]
        for term in flatterm:
            if isinstance(term, Wildcard) and not isinstance(term, SymbolWildcard):
                if last_wildcard is not None:
                    new_min_count = last_wildcard.min_count + term.min_count
                    new_fixed_size = last_wildcard.fixed_size and term.fixed_size
                    last_wildcard = Wildcard(new_min_count, new_fixed_size)
                else:
                    last_wildcard = term
            else:
                if last_wildcard is not None:
                    yield last_wildcard
                    last_wildcard = None
                yield term
        if last_wildcard is not None:
            yield last_wildcard

    def __str__(self):
        return ' '.join(map(self._term_str, self))

    def __repr__(self):
        return '[{!s}]'.format(', '.join(map(str, self)))


def _term_str(term: TermAtom) -> str:  # pragma: no cover
    """Return a string representation of a term atom."""
    if is_operation(term):
        return term.name + '('
    elif is_symbol_wildcard(term):
        return '*{!s}'.format(term.__name__)
    elif isinstance(term, Wildcard):
        return '*{!s}{!s}'.format(term.min_count, (not term.fixed_size) and '+' or '')
    elif term == Wildcard:
        return '*'
    else:
        return str(term)


class _State(Dict[TransitionLabel, Union['_State', List[T]]], Generic[T]):
    """An DFA state used by the :class:`DiscriminationNet`.

    This is a dict of transitions mapping terms of a :class:`FlatTerm` to new states.
    Each state has a unique :attr:`id`.

    A transition can also go to a terminal state that is a list of patterns.
    """

    _id = 1

    def __init__(self) -> None:
        super().__init__(self)
        self.id = _State._id
        _State._id += 1

    def _target_str(self, value: Union['_State', List[T]]) -> str:  # pragma: no cover
        """Return a string representation of a transition target."""
        if value is self:
            return 'self'
        elif isinstance(value, list):
            return '[{!s}]'.format(', '.join(map(str, value)))
        else:
            return str(value)

    @recursive_repr()
    def __repr__(self):
        return '{{STATE {!s}}}'.format(', '.join('{!s}:{!s}'.format(_term_str(term), self._target_str(target)))
                                       for term, target in self.items())


class _StateQueueItem(Generic[T]):
    """Internal data structure used by the product net algorithm.

    It contains a pair of states from each source net (:attr:`state1` and :attr:`state2`), their :attr:`ids <State.id>`
    or ``0`` if the state is ``None`` (:attr:`id1` and :attr:`id2`).

    It also keeps track of the operation nesting :attr:`depth` of the states. A state is
    uniquely identified by its state pair and depth. This is needed to combine patterns with
    varying nesting depths to distinguish between states that have the same states but different depth. While one of the
    original automatons uses a wildcard transition and the other an operation opening transition, the whole nested
    operation has to be processed.
    To track whether this process is complete, the :attr:`depth` is used.

    In addition, :attr:`fixed` tracks which of the two automata is using the wildcard transition. If it is set to ``1``,
    the first automaton is using it. If set to ``2``,  the second automaton is using it. Otherwise it will be set to
    ``0``. :attr:`fixed` can only be non-zero if the depth is greater than zero.
    """
    def __init__(self, state1: _State[T], state2: _State[T]) -> None:
        self.state1 = state1
        self.state2 = state2
        try:
            self.id1 = state1.id
        except AttributeError:
            self.id1 = 0
        try:
            self.id2 = state2.id
        except AttributeError:
            self.id2 = 0
        self.depth = 0
        self.fixed = 0

    @property
    def labels(self) -> Set[TransitionLabel]:
        """Return the set of transition labels to examine for this queue state.

        This is the union of the transition label sets for both states.
        However, if one of the states is fixed, it is excluded from this union and a wildcard transition is included
        instead. Also, when already in a failed state (one of the states is ``None``), the :const:`OPERATION_END` is
        also included.
        """
        labels = set() # type: Set[TransitionLabel]
        if self.state1 is not None and self.fixed != 1:
            labels.update(self.state1.keys())
        if self.state2 is not None and self.fixed != 2:
            labels.update(self.state2.keys())
        if self.fixed != 0:
            if self.fixed == 1 and self.state2 is None:
                labels.add(OPERATION_END)
            elif self.fixed == 2 and self.state1 is None:
                labels.add(OPERATION_END)
            labels.add(Wildcard)
        return labels

    def __repr__(self):
        return 'NQI({!r}, {!r}, {!r}, {!r}, {!r}, {!r})'.format(
            self.id1, self.id2, self.depth, self.fixed, self.state1, self.state2)


class DiscriminationNet(Generic[T]):
    """An automaton to distinguish which patterns match a given expression.

    This is a DFA with an implicit fail state whenever a transition is not actually defined.
    For every pattern added, an automaton is created and then the product automaton with the existing one is used as
    the new automaton.

    The matching assumes that patterns are linear, i.e. it will treat all variables as non-existent and only consider
    the wildcards.
    """

    def __init__(self):
        self._root = _State()

    def add(self, pattern: Expression, final_label: T=None) -> None:
        """TODO"""
        if final_label is None:
            final_label = pattern
        flatterm = FlatTerm(pattern)
        if pattern.is_syntactic or len(flatterm) == 1:
            net = self._generate_syntactic_net(flatterm, final_label)
        else:
            net = self._generate_net(flatterm, final_label)

        if self._root:
            self._root = self._product_net(self._root, net)
        else:
            self._root = net

    @staticmethod
    def _create_child_state(state: _State[T], label: TransitionLabel) -> _State[T]:
        new_state = _State()
        state[label] = new_state
        return new_state

    @classmethod
    def _generate_syntactic_net(cls, flatterm: FlatTerm, final_label: T) -> _State[T]:
        root = state = _State()

        for term in flatterm[:-1]:
            if isinstance(term, Wildcard):
                state = cls._generate_state_chain(state, Wildcard, term.min_count)
            else:
                state = cls._create_child_state(state, term)

        if isinstance(flatterm[-1], Wildcard):
            state = cls._generate_state_chain(state, Wildcard, flatterm[-1].min_count - 1)
            state[Wildcard] = [final_label]
        else:
            state[flatterm[-1]] = [final_label]

        return root

    @classmethod
    def _generate_state_chain(cls, state: _State[T], label: TransitionLabel, count: int) -> _State[T]:
        for _ in range(count):
            state = cls._create_child_state(state, label)
        return state

    @classmethod
    def _generate_net(cls, flatterm: FlatTerm, final_label: T) -> _State[T]:
        """Generates a DFA matching the given pattern."""
        # Capture the last sequence wildcard for every level of operation nesting on a stack
        # Used to add backtracking edges in case the "match" fails later
        last_wildcards = [None]
        # Generate a fail state for every level of nesting to backtrack to a sequence wildcard in a parent Expression
        # in case no match can be found
        fail_states = [None]
        root = state = _State()
        states = {root.id: root}

        for term in flatterm[:-1]:
            # For wildcards, generate a chain of #min_count Wildcard edges
            # If the wildcard is unbounded (fixed_size = False),
            # add a wildcard self loop at the end
            if isinstance(term, Wildcard):
                # Generate a chain of #min_count Wildcard edges
                for _ in range(term.min_count):
                    state = cls._create_child_state(state, Wildcard)
                    states[state.id] = state
                # If it is a sequence wildcard, add a self loop
                if not term.fixed_size:
                    state[Wildcard] = state
                    last_wildcards[-1] = state
            else:
                state = cls._create_child_state(state, term)
                states[state.id] = state
                if is_operation(term):
                    fail_state = None
                    if last_wildcards[-1] or fail_states[-1]:
                        fail_state = _State()
                        states[fail_state.id] = fail_state
                        fail_state[OPERATION_END] = last_wildcards[-1] or fail_states[-1]
                        fail_state[Wildcard] = fail_state
                    fail_states.append(fail_state)
                    last_wildcards.append(None)
                elif term == OPERATION_END:
                    fail_states.pop()
                    last_wildcards.pop()

            if last_wildcards[-1] != state:
                if last_wildcards[-1]:
                    state[EPSILON] = last_wildcards[-1]
                elif fail_states[-1]:
                    state[EPSILON] = fail_states[-1]

        assert not isinstance(flatterm[-1], Wildcard)
        state[flatterm[-1]] = [final_label]

        return cls._convert_nfa_to_dfa(root, states)

    @classmethod
    def _convert_nfa_to_dfa(cls, root: _State[T], states: Dict[int, _State[T]]) -> _State[T]:
        new_root = cls._epsilon_closure({root.id}, states)
        queue = [new_root]
        new_states = {new_root: _State()}

        while queue:
            state = queue.pop()
            labels = set().union(*(states[s].keys() for s in state))  # type: Set[TransitionLabel]
            new_state = new_states[state]

            for label in labels:
                if label is EPSILON:
                    continue
                target = cls._target_set(state, label, states)
                if isinstance(target, list):
                    new_state[label] = target
                else:
                    if target not in new_states:
                        new_states[target] = _State()
                        queue.append(target)

                    new_state[label] = new_states[target]

        return new_states[new_root]

    @staticmethod
    def _epsilon_closure(state: Set[int], states: Dict[int, _State[T]]) -> FrozenSet[int]:
        output = set(state)

        while True:
            to_add = set()
            for s in output:
                try:
                    new_state = states[s][EPSILON]
                    if new_state.id not in output:
                        to_add.add(new_state.id)
                except KeyError:
                    pass

            if to_add:
                output.update(to_add)
            else:
                break

        return frozenset(output)

    @classmethod
    def _target_set(cls, state: Set[int], label: TransitionLabel, states: Dict[int, _State[T]]) -> FrozenSet[int]:
        output = set()

        for s in state:
            if label in states[s]:
                if isinstance(states[s][label], list):
                    return states[s][label]
                output.add(states[s][label].id)
            if isinstance(label, Symbol):
                type_label = _get_symbol_wildcard_label(states[s], label)
                if type_label in states[s]:
                    # A symbol with an alternative symbol wildcard can never be the final edge in the automaton
                    # If it is, an invalid NFA was manually generated, that allows alternative expressions (OR) or has
                    # imbalanced nesting
                    assert not isinstance(states[s][type_label], list)
                    output.add(states[s][type_label].id)
            if Wildcard in states[s] and not is_operation(label) and label != OPERATION_END:
                # Trivial wildcard expressions are handled by the syntactic net generator
                assert not isinstance(states[s][Wildcard], list)
                output.add(states[s][Wildcard].id)

        return cls._epsilon_closure(output, states)

    @staticmethod
    def _get_next_state(state: _State[T], label: TransitionLabel, fixed: bool) -> Tuple[_State[T], bool]:
        if fixed:
            return state, False
        if state is not None:
            try:
                try:
                    return state[label], False
                except KeyError:
                    if label != OPERATION_END:
                        if isinstance(label, Symbol):
                            symbol_wildcard_key = _get_symbol_wildcard_label(state, label)
                            if symbol_wildcard_key is not None:
                                return state[symbol_wildcard_key], False
                        return state[Wildcard], True
            except KeyError:
                pass
        return None, False

    @classmethod
    def _product_net(cls, state1: _State[T], state2: _State[T]) -> _State[T]:
        root = _State()
        states = {(state1.id, state2.id, 0): root}
        queue = [_StateQueueItem(state1, state2)]

        while len(queue) > 0:
            current_state = queue.pop(0)
            state = states[(current_state.id1, current_state.id2, current_state.depth)]

            for label in list(current_state.labels):
                t1, with_wildcard1 = cls._get_next_state(current_state.state1, label, current_state.fixed == 1)
                t2, with_wildcard2 = cls._get_next_state(current_state.state2, label, current_state.fixed == 2)

                child_state = _StateQueueItem(t1, t2)
                child_state.depth = current_state.depth
                child_state.fixed = current_state.fixed

                if is_operation(label):
                    if current_state.fixed:
                        child_state.depth += 1
                    elif with_wildcard1:
                        child_state.fixed = 1
                        child_state.depth = 1
                        child_state.state1 = current_state.state1
                        child_state.id1 = current_state.id1
                    elif with_wildcard2:
                        child_state.fixed = 2
                        child_state.depth = 1
                        child_state.state2 = current_state.state2
                        child_state.id2 = current_state.id2
                elif label == OPERATION_END and current_state.fixed:
                    child_state.depth -= 1

                    if child_state.depth == 0:
                        if child_state.fixed == 1:
                            child_state.state1 = child_state.state1[Wildcard]
                            try:
                                child_state.id1 = child_state.state1.id
                            except AttributeError:
                                child_state.id1 = 0
                        elif child_state.fixed == 2:
                            child_state.state2 = child_state.state2[Wildcard]
                            try:
                                child_state.id2 = child_state.state2.id
                            except AttributeError:
                                child_state.id2 = 0
                        else:
                            raise AssertionError  # unreachable
                        child_state.fixed = 0

                if child_state.id1 != 0 or child_state.id2 != 0:
                    if (child_state.id1, child_state.id2, child_state.depth) not in states:
                        states[(child_state.id1, child_state.id2, child_state.depth)] = _State()
                        queue.append(child_state)

                    state[label] = states[(child_state.id1, child_state.id2, child_state.depth)]
                else:
                    if isinstance(child_state.state1, list) and isinstance(child_state.state2, list):
                        state[label] = child_state.state1 + child_state.state2
                    elif isinstance(child_state.state1, list):
                        state[label] = child_state.state1
                    elif isinstance(child_state.state2, list):
                        state[label] = child_state.state2
                    else:
                        # Unreachable, because the state (None, None) cannot be reached, as
                        # only labels which occur in at least one state are considered
                        raise AssertionError

        return root

    def match(self, expression: Expression) -> List[T]:
        flatterm = FlatTerm(expression) if isinstance(expression, Expression) else expression
        state = self._root
        depth = 0
        for term in flatterm:
            if depth > 0:
                if is_operation(term):
                    depth += 1
                elif term == OPERATION_END:
                    depth -= 1
            else:
                try:
                    try:
                        state = state[term]
                    except KeyError:
                        if is_operation(term):
                            depth = 1
                            state = state[Wildcard]
                        elif term == OPERATION_END:
                            return []
                        elif isinstance(term, Symbol):
                            symbol_wildcard_key = _get_symbol_wildcard_label(state, term)
                            state = state[symbol_wildcard_key or Wildcard]
                        else:
                            raise TypeError("Expression contains non-terminal atom: {!s}".format(expression))
                except KeyError:
                    return []

                if not isinstance(state, _State):
                    return state

        # Unreachable code: Unless the automaton got manually screwed up, it should be balanced in terms of opening and
        # closing symbols. Reading the expression with such an automaton will always hit a terminal node at the latest
        # after reading the last symbol in the expression term, so the loop will never finish normally.
        raise AssertionError

    def as_graph(self) -> Digraph:  # pragma: no cover
        dot = Digraph()

        nodes = set()
        queue = [self._root]
        while queue:
            state = queue.pop(0)
            nodes.add(state.id)
            dot.node('n{!s}'.format(state.id), '', {'shape': 'point'})

            for next_state in state.values():
                if isinstance(next_state, _State):
                    if next_state.id not in nodes:
                        queue.append(next_state)
                else:
                    l = '\n'.join(str(x) for x in next_state)
                    dot.node('l{!s}'.format(id(next_state)), l, {'shape': 'plaintext'})

        nodes = set()
        queue = [self._root]
        while queue:
            state = queue.pop(0)
            if state.id in nodes:
                continue
            nodes.add(state.id)

            for (label, other) in state.items():
                if isinstance(other, _State):
                    dot.edge('n{!s}'.format(state.id), 'n{!s}'.format(other.id), _term_str(label))
                    if other.id not in nodes:
                        queue.append(other)
                else:
                    dot.edge('n{!s}'.format(state.id), 'l{!s}'.format(id(other)), _term_str(label))

        return dot

if __name__ == '__main__':
    import doctest

    globs = {
        'f': Operation.new('f', Arity.variadic),
        'a': Symbol('a'),
        'b': Symbol('b'),
        'c': Symbol('c'),
        'x_': Variable.dot('x'),
        '_': Wildcard.dot(),
        '__': Wildcard.plus(),
        '___': Wildcard.star()
    }

    doctest.testmod(exclude_empty=True, extraglobs=globs)
