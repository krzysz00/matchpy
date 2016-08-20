# -*- coding: utf-8 -*-
import ast
import inspect
import itertools
import math
import re
from typing import Iterator, List, Sequence, Tuple, TypeVar, cast, Optional

T = TypeVar('T')

def partitions_with_limits(values : List[T], limits : List[Tuple[int, int]]) -> Iterator[Tuple[List[T], ...]]:
    limits = list(limits)
    count = len(values)
    varCount = count - sum([m for (m, _) in limits])
    counts = []
    
    for (minCount, maxCount) in limits:
        if maxCount > minCount + varCount:
            maxCount = minCount + varCount
        counts.append(list(range(minCount, maxCount + 1)))
                        
    for countPartition in itertools.product(*counts):
        if sum(countPartition) != count:
            continue
            
        v = []
        i = 0
        
        for c in countPartition:
            v.append(values[i:i+c])
            i += c
            
        yield tuple(v)   

def partitions_with_count(n, m):
    # H1: Initialize
    a = [1] * m
    a.append(-1) 
    a[0] = n - m + 1

    while True:
        while True:
            # H2: Visit
            yield a[:-1]

            if a[1] > a[0] - 1:
                break

            # H3: Tweak a[0] and a[1]
            a[0] -= 1
            a[1] += 1

        # H4: Find j
        j = 2
        s = a[0] + a[1] - 1

        while a[j] >= a[0] - 1:
            s += a[j]
            j += 1

        # H5: Increase a[j]
        if j >= m:
            return
        
        x = a[j] + 1
        a[j] = x
        j -= 1

        # H6: Tweak a[:j]
        while j > 0:
            a[j] = x
            s -= x
            j -= 1
        
        a[0] = s

def fixed_sum_vector_iter(min_vect : Sequence[int], max_vect : Sequence[int], total : int) -> Iterator[List[int]]:
    assert len(min_vect) == len(max_vect), 'len(min_vect) != len(max_vect)'
    assert all(minValue <= maxValue for minValue, maxValue in zip(min_vect, max_vect)), 'min_vect > max_vect'

    minSum = sum(min_vect)
    maxSum = sum(max_vect)

    if minSum > total or maxSum < total:
        return

    count = len(max_vect)

    if count <= 1:
        if len(max_vect) == 1:
            yield [total]
        else:
            yield []
        return

    remaining = total - minSum

    realMins = list(min_vect)
    realMaxs = list(max_vect)

    for i, (minimum, maximum) in enumerate(zip(min_vect, max_vect)):
        left_over_sum = sum(max_vect[:i]) + sum(max_vect[i+1:])
        if left_over_sum != math.inf:
            realMins[i] = max(total - left_over_sum, minimum)
        realMaxs[i] = min(remaining + minimum, maximum)

    values = list(realMins)

    remaining = total - sum(realMins)

    if remaining == 0:
        yield values
        return

    j = count - 1
    while remaining > 0:
        toAdd = min(realMaxs[j] - realMins[j], remaining)
        values[j] += toAdd
        remaining -= toAdd
        j -= 1

    while True:
        pos = count - 2
        yield values[:]
        while True:
            values[pos] += 1
            values[-1] -= 1
            if values[-1] < realMins[-1] or values[pos] > realMaxs[pos]:
                if pos == 0:
                    return
                variable_amount = values[pos] - realMins[pos] 
                values[pos] = realMins[pos] # reset current position
                values[-1] += variable_amount # reset last position

                if values[-1] > realMaxs[-1]:
                    remaining = values[-1] - realMaxs[-1] - 1
                    values[-1] = realMaxs[-1] + 1
                    j = count - 2
                    while remaining > 0:
                        toAdd = min(realMaxs[j] - values[j], remaining)
                        values[j] += toAdd
                        remaining -= toAdd
                        j -= 1
                pos -= 1
            else:
                break

def _count(values: Sequence[T]) -> Iterator[Tuple[T, int]]:
    last_value = None # type: T
    last_count = 0
    for value in sorted(values):
        if value != last_value:
            if last_count > 0:
                yield last_value, last_count
            last_value = value
            last_count = 1
        else:
            last_count += 1
    if last_count > 0:
        yield last_value, last_count

def commutative_partition_iter(values: Sequence[T], min_vect: Sequence[int], max_vect: Sequence[int]) -> Iterator[Tuple[List[T], ...]]:
    counts = list(_count(values))
    value_count = len(counts)
    iterators = [None] * value_count # type: List[Optional[Iterator[List[int]]]]
    pvalues = [None] * value_count # type: List[Optional[List[int]]]
    new_min = tuple(0 for _ in min_vect)
    iterators[0] = fixed_sum_vector_iter(new_min, max_vect, counts[0][1])
    try:
        pvalues[0] = iterators[0].__next__()
    except IndexError:
        return
    i = 1
    while True:
        try:
            while i < value_count:
                if iterators[i] is None:
                    iterators[i] = fixed_sum_vector_iter(new_min, max_vect, counts[i][1])
                pvalues[i] = iterators[i].__next__()
                i += 1
            sums = tuple(map(sum, zip(*pvalues))) # type: Tuple[int, ...]
            if all(minc <= s and s <= maxc for minc, s, maxc in zip(min_vect, sums, max_vect)):
                # cast is needed for mypy, as it can't infer the type of the empty list otherwise
                partiton = tuple(cast(List[T], []) for _ in range(len(min_vect))) # type: Tuple[List[T], ...]
                for cs, (v, _) in zip(pvalues, counts):
                    for j, c in enumerate(cs):
                        partiton[j].extend([v] * c)
                yield partiton
            i -= 1
        except StopIteration:
            #print('s', i)
            iterators[i] = None
            i -= 1
            if i < 0:
                return

def get_lambda_source(l):
    src = inspect.getsource(l)
    match = re.search("lambda.*?:(.*)$", src)

    if match is None:
        return l.__name__

    return match.group(1)

# http://stackoverflow.com/questions/12700893/how-to-check-if-a-string-is-a-valid-python-identifier-including-keyword-check
def isidentifier(ident):
    """Determines, if string is valid Python identifier."""

    # Smoke test — if it's not string, then it's not identifier, but we don't
    # want to just silence exception. It's better to fail fast.
    if not isinstance(ident, str):
        raise TypeError('expected str, but got {!r}'.format(type(ident)))

    # Resulting AST of simple identifier is <Module [<Expr <Name "foo">>]>
    try:
        root = ast.parse(ident)
    except SyntaxError:
        return False

    if not isinstance(root, ast.Module):
        return False

    if len(root.body) != 1:
        return False

    if not isinstance(root.body[0], ast.Expr):
        return False

    if not isinstance(root.body[0].value, ast.Name):
        return False

    if root.body[0].value.id != ident:
        return False

    return True

def extended_euclid(a: int, b: int) -> Tuple[int, int, int]:
    """Extended Euclidean algorithm that computes the Bézout coefficients as well as `gcd(a, b)`
    
    Returns `x, y, d` where `x` and `y` are a solution to `ax + by = d` and `d = gcd(a, b)`.
    `x` and `y` are a minimal pair of Bézout's coefficients.

    See `Extended Euclidean algorithm <https://en.wikipedia.org/wiki/Extended_Euclidean_algorithm>`_ or
    `Bézout's identity <https://en.wikipedia.org/wiki/B%C3%A9zout%27s_identity>`_ for more information.
    """
    if b == 0:
        return (1, 0, a)

    x0, y0, d = extended_euclid(b, a % b)
    x, y = y0, x0 - (a // b) * y0

    return (x, y, d)

def base_solution_linear(c: int, a: int, b: int) -> Iterator[Tuple[int, int]]:
    r"""Yields solution for a basic linear Diophantine equation of the form :math:`ax + by = c`.
    
    First, the equation is normalized by dividing :math:`a, b, c` by their gcd.
    Then, the extended Euclidean algorithm (:func:`extended_euclid`) is used to find a base solution :math:`(x_0, y_0)`.
    From that all non-negative solutions are generated by using that the general solution is :math:`(x_0 + b t, y_0 - a t)`.
    Hence, by adding or substracting :math:`a` resp. :math:`b` from the base solution, all solutions can be generated.
    Because the base solution is one of the minimal pairs of Bézout's coefficients, for all non-negative solutions 
    either :math:`t \geq 0` or :math:`t \leq 0` must hold. Also, all the non-negative solutions are consecutive with
    respect to :math:`t`. Therefore, all non-negative solutions can be generated efficiently from the base solution.
    """
    d = math.gcd(a, math.gcd(b, c))
    a = a // d
    b = b // d
    c = c // d

    if c == 0:
        yield (0, 0)
    else:
        x0, y0, d = extended_euclid(a, b)

        # If c is not divisible by gcd(a, b), then there is no solution
        if c % d != 0:
            return

        x, y = c * x0, c * y0

        if x <= 0:
            while y >= 0:
                if x >= 0:
                    yield (x, y)
                x += b
                y -= a
        else:
            while x >= 0:
                if y >= 0:
                    yield (x, y)
                x -= b
                y += a

def solve_linear_diop(total: int, *coeffs: int) -> Iterator[Tuple[int, ...]]:
    r"""Generator for the solutions of a linear Diophantine equation of the form :math:`c_1 x_1 + \dots + c_n x_n = total`

    `coeffs` are the coefficients `c_i`.
    
    If there are at most two coefficients, :func:`base_solution_linear` is used to find the solutions.
    Otherwise, the solutions are found recursively, by reducing the number of variables in each recursion:
    
    1. Compute :math:`d := gcd(c_2, \dots , c_n)`
    2. Solve :math:`c_1 x + d y = total`
    3. Recursively solve :math:`c_2 x_2 + \dots + c_n x_n = y` for each solution for `y`
    4. Combine these solutions to form a solution for the whole equation
    """
    if len(coeffs) == 0:
        return
    if len(coeffs) == 1:
        if total % coeffs[0] == 0:
            yield (total // coeffs[0], )
        return
    if len(coeffs) == 2:
        yield from base_solution_linear(total, coeffs[0], coeffs[1])
        return

    # calculate gcd(coeffs[1:])
    remainder_gcd = math.gcd(coeffs[1], coeffs[2])
    for coeff in coeffs[3:]:
        remainder_gcd = math.gcd(remainder_gcd, coeff)

    # solve coeffs[0] * x + remainder_gcd * y = total
    for coeff0_solution, remainder_gcd_solution in base_solution_linear(total, coeffs[0], remainder_gcd):
        # use the solutions for y to solve the remaining variables recursively
        for remainder_solution in solve_linear_diop(remainder_gcd_solution, *coeffs[1:]):
            yield (coeff0_solution, ) + remainder_solution

def _match_value_repr_str(value):
    if type(value) == list:
        return '(%s)' % (', '.join(str(x) for x in value))
    return str(value)

def match_repr_str(match):
    return ', '.join('%s: %s' % (k, _match_value_repr_str(v)) for k, v in match.items())

if __name__ == '__main__':
    print(list(solve_linear_diop(5, 2, 3, 1)))
    #for a in range(1, 6):
    #    for b in range(a, 6):
    #        for c in range(1, 16):
    #            print('%d*x + %d*y = %d' % (a, b, c), list(base_solution_linear(c, a, b)))
    #print(list(fixed_sum_vector_iter((0,1,1), (8000,2,2), 5)))
    # values = ('a', 'a', 'b', 'b', 'c')
    # mins = (0, 2)
    # maxs = (math.inf, math.inf)
    # for p in commutative_partition_iter(values, mins, maxs):
    #     print(p)
