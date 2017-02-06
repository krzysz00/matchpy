# -*- coding: utf-8 -*-
"""This module contains various many-to-one matchers for syntactic patterns:

- There `DiscriminationNet` class that is a many-to-one matcher for syntactic patterns.
- The `SequenceMatcher` can be used to match patterns with a common surrounding operation with some fixed
  syntactic patterns.
- The `FlatTerm` representation for an expression flattens the expression's tree structure and allows faster preoder
  traversal.

Furthermore, the module contains some utility functions for working with flatterms.
"""

import itertools
from reprlib import recursive_repr
from typing import (Any, Dict, FrozenSet, Generic, Iterator, List, Optional, Sequence, Set, Tuple, Type, TypeVar, Union)

from graphviz import Digraph

from ..expressions.expressions import Expression, Operation, Symbol, SymbolWildcard, Variable, Wildcard
from ..expressions.substitution import Substitution
from ..expressions.constraints import MultiConstraint
from ..utils import slot_cached_property

__all__ = ['FlatTerm', 'is_operation', 'is_symbol_wildcard', 'DiscriminationNet', 'SequenceMatcher']

T = TypeVar('T')

OPERATION_END = ')'
"""Constant used to represent the end of an operation in a :class:`FlatTerm` and :class:`DiscriminationNet`."""

EPSILON = 'ε'
"""Constant used to label an epsilon transition for the :class:`DiscriminationNet`."""


def is_operation(term: Any) -> bool:
    """Return True iff the given term is a subclass of :class:`.Operation`."""
    return isinstance(term, type) and issubclass(term, Operation)


def is_symbol_wildcard(term: Any) -> bool:
    """Return True iff the given term is a subclass of :class:`.Symbol`."""
    return isinstance(term, type) and issubclass(term, Symbol)


def _get_symbol_wildcard_label(state: '_State', symbol: Symbol) -> Type[Symbol]:
    """Return the transition target for the given symbol type from the the given state or None if it does not exist."""
    return next((t for t in state.keys() if is_symbol_wildcard(t) and isinstance(symbol, t)), None)


TermAtom = Union[Symbol, Wildcard, Type[Operation], Type[Symbol], type(OPERATION_END)]
TransitionLabel = Union[Symbol, Type[Operation], Type[Symbol], Type[Wildcard], type(OPERATION_END), type(EPSILON)]


class FlatTerm(Sequence[TermAtom]):
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
    >>> _s = Wildcard.symbol(SpecialSymbol)
    >>> FlatTerm(_s)
    [<class '__main__.SpecialSymbol'>]


    Symbol wildcards are also not merged like other wildcards, because they can never be sequence wildcards:

    >>> FlatTerm(f(_, _s))
    [f, _, <class '__main__.SpecialSymbol'>, )]
    """

    __slots__ = '_terms', '_is_syntactic'

    def __init__(self, expression: Union[Expression, Sequence[TermAtom]]) -> None:
        if isinstance(expression, Expression):
            expression = self._combined_wildcards_iter(self._flatterm_iter(expression))
        self._terms = tuple(expression)

    def __getitem__(self, index):
        return self._terms[index]

    def __len__(self):
        return len(self._terms)

    def __contains__(self, term):
        return term in self._terms

    def __iter__(self):
        return iter(self._terms)

    def __add__(self, other):
        if isinstance(other, FlatTerm):
            return FlatTerm(self._terms + other._terms)
        if isinstance(other, Sequence):
            return FlatTerm(self._terms + tuple(other))
        return NotImplemented

    def __eq__(self, other):
        if isinstance(other, FlatTerm):
            return self._terms == other._terms
        return NotImplemented

    @slot_cached_property('_is_syntactic')
    def is_syntactic(self):
        """True, iff the flatterm is :term:`syntactic`."""
        for term in self._terms:
            if isinstance(term, Wildcard) and not term.fixed_size:
                return False
            if is_operation(term) and (term.commutative or term.associative):
                return False
        return True

    @classmethod
    def empty(cls) -> 'FlatTerm':
        """An empty flatterm."""
        return cls([])

    @classmethod
    def merged(cls, *flatterms: 'FlatTerm') -> 'FlatTerm':
        """Concatenate the given flatterms to a single flatterm.

        Args:
            *flatterms:
                The flatterms which are concatenated.

        Returns:
            The concatenated flatterms.
        """
        return cls(cls._combined_wildcards_iter(sum(flatterms, cls.empty())))

    @classmethod
    def _flatterm_iter(cls, expression: Expression) -> Iterator[TermAtom]:
        """Generator that yields the atoms of the expressions in prefix notation with operation end markers."""
        if isinstance(expression, Variable):
            yield from cls._flatterm_iter(expression.expression)
        elif isinstance(expression, Operation):
            yield type(expression)
            for operand in expression.operands:
                yield from cls._flatterm_iter(operand)
            yield OPERATION_END
        elif isinstance(expression, SymbolWildcard):
            yield expression.symbol_type
        elif isinstance(expression, (Symbol, Wildcard)):
            yield expression
        else:
            assert False, "Unreachable unless a new unsupported expression type is added."

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
        return ' '.join(map(_term_str, self))

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


class _State(Dict[TransitionLabel, '_State'], Generic[T]):
    """An DFA state used by the :class:`DiscriminationNet`.

    This is a dict of transitions mapping terms of a :class:`FlatTerm` to new states.
    Each state has a unique :attr:`id`.
    """

    _id = 1

    def __init__(self, payload=None) -> None:
        super().__init__(self)
        self.id = _State._id
        _State._id += 1
        self.payload = payload if payload is not None else []

    def _target_str(self, value: '_State') -> str:  # pragma: no cover
        """Return a string representation of a transition target."""
        if value is self:
            return 'self'
        else:
            return str(value)

    @recursive_repr()
    def __repr__(self):
        return '{{STATE {!s}: {!s}}}'.format(
            self.payload,
            ', '.join('{!s}:{!s}'.format(_term_str(term), self._target_str(target)) for term, target in self.items())
        )


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
        self.payload = []
        try:
            self.id1 = state1.id
            self.payload.extend(state1.payload)
        except AttributeError:
            self.id1 = 0
        try:
            self.id2 = state2.id
            self.payload.extend(state2.payload)
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
        labels = set()  # type: Set[TransitionLabel]
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
            self.id1, self.id2, self.depth, self.fixed, self.state1, self.state2
        )


class DiscriminationNet(Generic[T]):
    """An automaton to distinguish which patterns match a given expression.

    This is a DFA with an implicit fail state whenever a transition is not actually defined.
    For every pattern added, an automaton is created and then the product automaton with the existing one is used as
    the new automaton.

    The matching assumes that patterns are linear, i.e. it will treat all variables as non-existent and only consider
    the wildcards.
    """

    def __init__(self, *patterns: Expression) -> None:
        """
        Args:
            *patterns:
                Optional pattern to initially add to the discrimination net.
        """
        self._root = _State()
        self._patterns = []
        for pattern in patterns:
            self.add(pattern)

    def add(self, pattern: Union[Expression, FlatTerm], final_label: T=None) -> int:
        """Add a pattern to the discrimination net.

        Args:
            pattern:
                The pattern which is added to the DiscriminationNet. If an expression is given, it will be converted to
                a `FlatTerm` for internal processing. You can also pass a `FlatTerm` directly.
            final_label:
                A label that is returned if the pattern matches when using :meth:`match`. This will default to the
                pattern itself.

        Returns:
            The index of the newly added pattern. This is used internally to later to get the pattern and its final
            label once a match is found.
        """
        index = len(self._patterns)
        self._patterns.append((pattern, final_label))
        flatterm = FlatTerm(pattern) if not isinstance(pattern, FlatTerm) else pattern
        if pattern.is_syntactic or len(flatterm) == 1:
            net = self._generate_syntactic_net(flatterm, index)
        else:
            net = self._generate_net(flatterm, index)

        if self._root:
            self._root = self._product_net(self._root, net)
        else:
            self._root = net
        return index

    @staticmethod
    def _create_child_state(state: _State[T], label: TransitionLabel) -> _State[T]:
        new_state = _State()
        state[label] = new_state
        return new_state

    @classmethod
    def _generate_syntactic_net(cls, flatterm: FlatTerm, final_label: T) -> _State[T]:
        root = state = _State()

        for term in flatterm:
            if isinstance(term, Wildcard):
                state = cls._generate_state_chain(state, Wildcard, term.min_count)
            else:
                state = cls._create_child_state(state, term)

        state.payload = [final_label]

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
        operand_counts = [0]
        root = state = _State()
        states = {root.id: root}

        for term in flatterm:
            if operand_counts[-1] >= 0:
                operand_counts[-1] += 1

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
                    operand_counts[-1] = -1
            else:
                state = cls._create_child_state(state, term)
                states[state.id] = state
                if is_operation(term):
                    fail_state = None
                    if last_wildcards[-1] or fail_states[-1]:
                        last_fail_state = (
                            fail_states[-1]
                            if not isinstance(fail_states[-1], list) else fail_states[-1][operand_counts[-1]]
                        )
                        if term.arity.fixed_size:
                            fail_state = _State()
                            states[fail_state.id] = fail_state
                            new_fail_states = [fail_state]
                            for _ in range(term.arity.min_count):
                                new_fail_state = _State()
                                states[new_fail_state.id] = new_fail_state
                                fail_state[Wildcard] = new_fail_state
                                fail_state = new_fail_state
                                new_fail_states.append(new_fail_state)
                            fail_state[OPERATION_END] = last_wildcards[-1] or last_fail_state
                            fail_state = new_fail_states
                        else:
                            fail_state = _State()
                            states[fail_state.id] = fail_state
                            fail_state[OPERATION_END] = last_wildcards[-1] or last_fail_state
                            fail_state[Wildcard] = fail_state
                    fail_states.append(fail_state)
                    last_wildcards.append(None)
                    operand_counts.append(0)
                elif term == OPERATION_END:
                    fail_states.pop()
                    last_wildcards.pop()
                    operand_counts.pop()

            if last_wildcards[-1] != state:
                if last_wildcards[-1]:
                    state[EPSILON] = last_wildcards[-1]
                elif fail_states[-1]:
                    last_fail_state = (
                        fail_states[-1]
                        if not isinstance(fail_states[-1], list) else fail_states[-1][operand_counts[-1]]
                    )
                    state[EPSILON] = last_fail_state

        state.payload = [final_label]

        return cls._convert_nfa_to_dfa(root, states)

    @staticmethod
    def _create_state(state_set: Set[int], states: Dict[int, _State[T]]) -> _State[T]:
        payload = set()

        for state in state_set:
            payload.update(states[state].payload)

        return _State(list(payload))

    @classmethod
    def _convert_nfa_to_dfa(cls, root: _State[T], states: Dict[int, _State[T]]) -> _State[T]:
        new_root = cls._epsilon_closure({root.id}, states)
        queue = [new_root]
        new_states = {new_root: cls._create_state(new_root, states)}

        while queue:
            state = queue.pop()
            labels = set().union(*(states[s].keys() for s in state))  # type: Set[TransitionLabel]
            new_state = new_states[state]

            for label in labels:
                if label is EPSILON:
                    continue
                target = cls._target_set(state, label, states)
                if target not in new_states:
                    new_states[target] = cls._create_state(target, states)
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
                output.add(states[s][label].id)
            if isinstance(label, Symbol):
                type_label = _get_symbol_wildcard_label(states[s], label)
                if type_label in states[s]:
                    # A symbol with an alternative symbol wildcard can never be the final edge in the automaton
                    # If it is, an invalid NFA was manually generated, that allows alternative expressions (OR) or has
                    # imbalanced nesting
                    output.add(states[s][type_label].id)
            if Wildcard in states[s] and not is_operation(label) and label != OPERATION_END:
                # Trivial wildcard expressions are handled by the syntactic net generator
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
                        child_state.payload = child_state.state2.payload + current_state.state1.payload
                    elif with_wildcard2:
                        child_state.fixed = 2
                        child_state.depth = 1
                        child_state.state2 = current_state.state2
                        child_state.id2 = current_state.id2
                        child_state.payload = child_state.state1.payload + current_state.state2.payload
                elif label == OPERATION_END and current_state.fixed:
                    child_state.depth -= 1

                    if child_state.depth == 0:
                        if child_state.fixed == 1:
                            child_state.state1 = child_state.state1[Wildcard]
                            child_state.id1 = child_state.state1.id
                            child_state.payload.extend(child_state.state1.payload)
                        elif child_state.fixed == 2:
                            child_state.state2 = child_state.state2[Wildcard]
                            child_state.id2 = child_state.state2.id
                            child_state.payload.extend(child_state.state2.payload)
                        else:
                            raise AssertionError  # unreachable
                        child_state.fixed = 0

                if (child_state.id1, child_state.id2, child_state.depth) not in states:
                    states[(child_state.id1, child_state.id2, child_state.depth)] = _State(child_state.payload)
                    queue.append(child_state)

                state[label] = states[(child_state.id1, child_state.id2, child_state.depth)]

        return root

    def _match(self, subject: Union[Expression, FlatTerm], collect: bool=False,
               first=False) -> List[Tuple[Expression, T]]:
        flatterm = FlatTerm(subject) if isinstance(subject, Expression) else subject
        state = self._root
        depth = 0
        result = state.payload[:]
        for term in flatterm:
            if depth > 0:
                if is_operation(term):
                    depth += 1
                elif term == OPERATION_END:
                    depth -= 1
            else:
                if first and state.payload:
                    return state.payload[:]
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
                            raise TypeError("Subject {} contains non-terminal atom: {}".format(subject, term))
                except KeyError:
                    return result if collect else []

                result.extend(state.payload)

        return result if collect else state.payload[:]

    def match(self, subject: Union[Expression, FlatTerm]) -> Iterator[Tuple[T, Substitution]]:
        """Match the given subject against all patterns in the net.

        Args:
            subject:
                The subject that is matched. Must be constant.

        Yields:
            A tuple :code:`(final label, substitution)`, where the first component is the final label associated with
            the pattern as given when using :meth:`add()` and the second one is the match substitution.
        """
        for index in self._match(subject):
            pattern, label = self._patterns[index]
            subst = Substitution()
            if subst.extract_substitution(subject, pattern):
                constraint = MultiConstraint.create(*(e.constraint for e, _ in pattern.preorder_iter()))
                if constraint is None or constraint(subst):
                    yield label, subst

    def as_graph(self) -> Digraph:  # pragma: no cover
        """Renders the discrimination net as graphviz digraph."""
        dot = Digraph()

        nodes = set()
        queue = [self._root]
        while queue:
            state = queue.pop(0)
            if not state.payload:
                dot.node('n{!s}'.format(state.id), '', {'shape': ('circle' if state else 'doublecircle')})
            else:
                dot.node('n{!s}'.format(state.id), '\n'.join(map(str, state.payload)), {'shape': 'box'})

            for next_state in state.values():
                if next_state.id not in nodes:
                    queue.append(next_state)
                    nodes.add(state.id)

        nodes = set()
        queue = [self._root]
        while queue:
            state = queue.pop(0)
            if state.id in nodes:
                continue
            nodes.add(state.id)

            for (label, other) in state.items():
                dot.edge('n{!s}'.format(state.id), 'n{!s}'.format(other.id), _term_str(label))
                if other.id not in nodes:
                    queue.append(other)

        return dot


class SequenceMatcher:
    r"""A matcher that matches many :term:`syntactic` patterns in a surrounding sequence.

    It can match patterns that have the form :math:`f(x^*, s_1, \dots, s_n, y^*)` where

    - :math:`f` is a non-commutative operation,
    - :math:`x^*, y^*` are star sequence wildcards or variables (they can be the same of different), and
    - all the :math:`s_i` are syntactic patterns.

    After adding these patterns with `add()`, they can be matched simultaneously against a subject with `match()`.
    Note that all patterns matched by one sequence matcher must have the same outer operation :math:`f`.

    Attributes:
        operation:
            The outer operation that all patterns have in common. Is set automatically when adding the first pattern
            and is check for all following patterns.
    """

    __slots__ = ('_net', '_patterns', 'operation')

    def __init__(self, *patterns: Expression) -> None:
        """
        Args:
            *patterns:
                Initial patterns to add to the sequence matcher.
        """
        self._net = DiscriminationNet()
        self._patterns = []
        self.operation = None
        for pattern in patterns:
            self.add(pattern)

    def add(self, pattern: Expression) -> int:
        """Add a pattern that will be recognized by the matcher.

        Args:
            pattern:
                The pattern to add.

        Returns:
            An internal index for the pattern.

        Raises:
            ValueError:
                If the pattern does not have the correct form.
            TypeError:
                If the pattern is not a non-commutative operation.
        """
        if self.operation is None:
            if not isinstance(pattern, Operation) or pattern.commutative:
                raise TypeError("Pattern must be a non-commutative operation.")
            self.operation = type(pattern)
        elif not isinstance(pattern, self.operation):
            raise TypeError(
                "All patterns must be the same operation, expected {} but got {}".
                format(self.operation, type(pattern))
            )

        if len(pattern.operands) < 3:
            raise ValueError("Pattern has not enough operands.")

        first_name = self._check_wildcard_and_get_name(pattern.operands[0])
        last_name = self._check_wildcard_and_get_name(pattern.operands[-1])

        index = len(self._patterns)
        self._patterns.append((pattern, first_name, last_name))

        flatterm = FlatTerm.merged(*(FlatTerm(o) for o in pattern.operands[1:-1]))
        self._net.add(flatterm, index)

        return index

    @staticmethod
    def _check_wildcard_and_get_name(operand):
        name = None
        if isinstance(operand, Variable):
            name = operand.name
            operand = operand.expression

        if not isinstance(operand, Wildcard) or operand.fixed_size or operand.min_count > 0:
            raise ValueError('Expected a star wildcard, got {!s}.'.format(operand))

        return name

    @classmethod
    def can_match(cls, pattern: Expression) -> bool:
        """Check if a pattern can be matched with a sequence matcher.

        Args:
            pattern:
                The pattern to check.

        Returns:
            True, iff the pattern can be matched with a sequence matcher.
        """
        if not isinstance(pattern, Operation) or pattern.commutative:
            return False

        if len(pattern.operands) < 3:
            return False

        try:
            cls._check_wildcard_and_get_name(pattern.operands[0])
            cls._check_wildcard_and_get_name(pattern.operands[-1])
        except ValueError:
            return False

        return True

    def match(self, subject: Expression) -> Iterator[Tuple[Expression, Substitution]]:
        """Match the given subject against all patterns in the sequence matcher.

        Args:
            subject:
                The subject that is matched. Must be constant.

        Yields:
            A tuple :code:`(pattern, substitution)` for every matching pattern.
        """
        if not isinstance(subject, self.operation):
            return

        flatterms = [FlatTerm(o) for o in subject.operands]

        for i in range(len(flatterms)):
            flatterm = FlatTerm.merged(*flatterms[i:])

            for index in self._net._match(flatterm, first=True):
                match_index = self._net._patterns[index][1]
                pattern, first_name, last_name = self._patterns[match_index]
                operand_count = len(pattern.operands) - 2
                expr_operands = subject.operands[i:i + operand_count]
                patt_operands = pattern.operands[1:-1]

                substitution = Substitution()
                if not all(itertools.starmap(substitution.extract_substitution, zip(expr_operands, patt_operands))):
                    continue

                try:
                    if first_name is not None:
                        substitution.try_add_variable(first_name, tuple(subject.operands[:i]))
                    if last_name is not None:
                        substitution.try_add_variable(last_name, tuple(subject.operands[i + operand_count:]))
                except ValueError:
                    continue

                yield pattern, substitution

    def as_graph(self) -> Digraph:  # pragma: no cover
        """Renders the underlying discrimination net as graphviz digraph."""
        return self._net.as_graph()
