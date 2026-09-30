"""Joint selection of an integer clock offset and an order-preserving pairing.

Two probes record pulse times ``A`` and ``B`` (strictly increasing integers,
nanoseconds).  We must choose a *single* integer offset ``d`` from a closed
interval ``[offset_min, offset_max]`` and a one-to-one order-preserving
matching between the two sequences, lexicographically optimising:

    1. maximise the number of pairs;
    2. minimise  sum |a_i - (b_j + d)|   over the pairs;
    3. minimise  max |a_i - (b_j + d)|   over the pairs;

then breaking ties by the smallest offset and by the lexicographically
smallest sequence of input indices.

A pair (i, j) is admissible at offset d iff |c_ij - d| <= tolerance, where
c_ij = a_i - b_j, i.e. d lies in the integer window [c_ij - T, c_ij + T].

The offset interval may span 2,000,000,000 nanoseconds, so we never scan it
nanosecond by nanosecond.  Instead we build a finite, provably sufficient set
of candidate offsets and run the O(n*m) matching DP once per candidate:

* c_ij - T, c_ij, c_ij + T and c_ij + T + 1 for every edge (i, j):
  feasibility-window boundaries (first/last feasible integer and first
  infeasible one) and residual kinks.  A maximum-pair matching feasible at
  any offset is also feasible at its window's boundary, and the absolute-
  residual sum's minimiser is either a median matched c_ij or, when the
  median plateau lies outside the feasible window, a clamped boundary
  c_ij +/- T -- so every optimum of objectives 1 and 2 lies on these points.
* floor/ceil of (c_p + c_q) / 2 for every pair of *co-orderable* edges
  (i,j),(i',j') that can occur together in an order-preserving matching --
  strictly i<i' and j<j', or vice versa -- restricted to offsets at which
  both edges are within tolerance (|c_p - c_q| <= 2T).  For any fixed
  matching, its largest absolute residual is max(c_max - d, d - c_min), whose
  integer minimiser is the (possibly half-integer) midpoint of two matched
  edges, so every objective-3 optimum is one of these points.
* the interval endpoints.

There are at most 4*n*m + 2 + O((n*m)^2) such values before filtering; with
n, m <= 24 the co-order and |c - c'| <= 2T filters keep only a few thousand
candidates (worst measured case under one second), and every visited offset is
derived from pairing critical values -- never from scanning.

Optional "consecutive gap" limits
---------------------------------

When enabled with per-side limits g_a, g_b >= 0, two consecutive matched
pairs (i, j) < (i', j') may only be adjacent when both
``i' - i - 1 <= g_a`` and ``j' - j - 1 <= g_b`` (pulses skipped between
them); pulses before the first pair and after the last pair are free.  This
is a purely *index* constraint, so it does not change the candidate-offset
set above: at every candidate offset the matching problem is solved jointly
as a chain DP with rectangle-maximum predecessor queries (monotone deques,
O(n*m) per offset) -- never by taking the unconstrained optimum and deleting
broken segments afterwards.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Optional, Sequence, Tuple

# A pairing's lexicographic objective used *inside* the DP, maximised:
#   (pair_count, -abs_sum, -max_abs_residual, index_key)
# ``max`` on this tuple implements: more pairs, smaller abs sum, smaller
# largest absolute residual, then lexicographically smallest paired indices.
Objective = Tuple[int, int, int, Tuple[Tuple[int, int], ...]]


def _empty_objective() -> Objective:
    return (0, 0, 0, ())


def best_pairing_at(
    c: Sequence[Sequence[int]], tol: int
) -> Tuple[Objective, List[Tuple[int, int]]]:
    """Optimal order-preserving matching for a fixed offset.

    ``c[i][j] = a_i - b_j - offset`` is the signed residual that pairing
    (i, j) would have at this offset.  Standard LCS-style DP with three
    incoming edges (skip A_i, skip B_j, pair i with j); indices start at 0.
    """
    n = len(c)
    m = len(c[0]) if n else 0

    dp: List[List[Optional[Objective]]] = [
        [None] * (m + 1) for _ in range(n + 1)
    ]
    parent: List[List[Optional[Tuple[int, int, bool]]]] = [
        [None] * (m + 1) for _ in range(n + 1)
    ]
    dp[0][0] = _empty_objective()

    for i in range(n + 1):
        for j in range(m + 1):
            if i == 0 and j == 0:
                continue
            best: Optional[Tuple[Objective, Tuple[int, int, bool]]] = None

            if i > 0 and dp[i - 1][j] is not None:
                best = (dp[i - 1][j], (i - 1, j, False))
            if j > 0 and dp[i][j - 1] is not None:
                cand = (dp[i][j - 1], (i, j - 1, False))
                if best is None or cand[0] > best[0]:
                    best = cand
            if i > 0 and j > 0 and dp[i - 1][j - 1] is not None:
                e = c[i - 1][j - 1]
                if -tol <= e <= tol:
                    p = dp[i - 1][j - 1]
                    assert p is not None
                    ae = e if e >= 0 else -e
                    cand_obj: Objective = (
                        p[0] + 1,
                        p[1] - ae,
                        min(p[2], -ae),
                        p[3] + ((i - 1, j - 1),),
                    )
                    cand = (cand_obj, (i - 1, j - 1, True))
                    if best is None or cand[0] > best[0]:
                        best = cand

            if best is not None:
                dp[i][j] = best[0]
                parent[i][j] = best[1]

    final = dp[n][m]
    assert final is not None

    pairs: List[Tuple[int, int]] = []
    i, j = n, m
    while i > 0 or j > 0:
        edge = parent[i][j]
        assert edge is not None
        pi, pj, used = edge
        if used:
            pairs.append((i - 1, j - 1))
        i, j = pi, pj
    pairs.reverse()
    return final, pairs


def best_pairing_constrained(
    A: Sequence[int],
    B: Sequence[int],
    offset: int,
    tol: int,
    max_gap_a: int,
    max_gap_b: int,
) -> Tuple[Objective, List[Tuple[int, int]]]:
    """Optimal order-preserving matching with consecutive-gap limits.

    For two consecutive matched pairs ``(i, j)`` and ``(i', j')`` (i < i',
    j < j'), the pulses skipped on each side are ``i' - i - 1`` on A and
    ``j' - j - 1`` on B; both must be within the given limits.  Pulses
    before the first pair and after the last pair are unrestricted.

    The matching is solved jointly as a chain DP: a state is the best chain
    ending in edge ``(i, j)``; its predecessor is the best chain ending in
    the rectangle ``[i-ga-1, i-1] x [j-gb-1, j-1]``.  Each column holds a
    monotone deque over its active row window, and a global deque over the
    active columns answers the rectangle maximum in amortised O(1), so the
    whole DP is O(n*m).
    """
    n = len(A)
    m = len(B)

    # best[i][j] is the lightweight objective of the best chain whose last
    # edge is (i, j), or None when (i, j) is infeasible at this offset.
    best: List[List[Optional[Objective]]] = [
        [None] * m for _ in range(n)
    ]
    parent: List[List[Optional[Tuple[int, int]]]] = [
        [None] * m for _ in range(n)
    ]

    # Per-column (j) structures for the row window of start predecessors:
    #   col_val[j][i] = best[i][j] (None if empty),
    #   col_deq[j]     = deque of rows i' in the current window
    #                    [max(0, i-ga-1), i-1], values strictly decreasing.
    col_val: List[List[Optional[Objective]]] = [
        [None] * n for _ in range(m)
    ]
    col_deq: List[Deque[int]] = [deque() for _ in range(m)]
    # Global deque of columns j' in [max(0, j-gb-1), j-1] whose *window*
    # maximum col_val[j'][col_deq[j'][0]] is strictly decreasing.
    global_deq: Deque[int] = deque()

    def col_max(j: int) -> Optional[Objective]:
        dq = col_deq[j]
        return col_val[j][dq[0]] if dq else None

    def col_push(j: int) -> None:
        """Insert column j into the global deque (its window max is final)."""
        v = col_max(j)
        if v is None:
            return
        while global_deq and col_max(global_deq[-1]) <= v:
            global_deq.pop()
        global_deq.append(j)

    for i in range(n):
        a = A[i]
        row_lo = max(0, i - max_gap_a - 1)

        # Prepare every column's row window [row_lo, row_hi] before the
        # global deque (reset per row) is built left to right.
        for j in range(m):
            dq = col_deq[j]
            if i > 0:
                # Extend the window with newly eligible start row i-1.
                sr = i - 1
                v = col_val[j][sr]
                if v is not None:
                    while dq and col_val[j][dq[-1]] <= v:
                        dq.pop()
                    dq.append(sr)
            # Drop starts that fell below the window's lower edge.
            while dq and dq[0] < row_lo:
                dq.popleft()

        global_deq.clear()
        for j in range(m):
            e = a - B[j] - offset
            if -tol <= e <= tol:
                pred: Optional[Objective] = None
                pred_pos: Optional[Tuple[int, int]] = None
                if global_deq:
                    pj = global_deq[0]
                    pred = col_max(pj)
                    assert pred is not None
                    pred_pos = (col_deq[pj][0], pj)
                if pred is None:
                    chain = (1, -(abs(e)), -abs(e), ((i, j),))
                else:
                    assert pred_pos is not None
                    ae = e if e >= 0 else -e
                    chain = (
                        pred[0] + 1,
                        pred[1] - ae,
                        min(pred[2], -ae),
                        pred[3] + ((i, j),),
                    )
                best[i][j] = chain
                parent[i][j] = pred_pos
                col_val[j][i] = chain

            # Column j becomes an eligible predecessor for later columns;
            # its window over this row is final once computed above.
            col_push(j)

            # The next cell j+1 may only start at columns >= j+1-gb-1.
            next_lo = max(0, (j + 1) - max_gap_b - 1)
            while global_deq and global_deq[0] < next_lo:
                global_deq.popleft()

    # Pick the globally best chain endpoint (the trailing pulses are free).
    end: Optional[Tuple[int, int]] = None
    final: Optional[Objective] = None
    for i in range(n):
        for j in range(m):
            v = best[i][j]
            if v is not None and (final is None or v > final):
                final = v
                end = (i, j)

    pairs: List[Tuple[int, int]] = []
    if end is not None:
        pos: Optional[Tuple[int, int]] = end
        while pos is not None:
            pairs.append(pos)
            pos = parent[pos[0]][pos[1]]
        pairs.reverse()
    chain_obj: Objective = final if final is not None else _empty_objective()
    return chain_obj, pairs


def _residual_matrix(A: Sequence[int], B: Sequence[int], offset: int):
    return [[a - b - offset for b in B] for a in A]


def _candidate_offsets(
    A: Sequence[int], B: Sequence[int], tol: int, lo: int, hi: int
) -> List[int]:
    """Finite, provably sufficient set of offsets to evaluate.

    See the module docstring for why the global optimum must lie in this set.
    """
    # Every edge with its raw c_ij = a_i - b_j.
    edges: List[Tuple[int, int, int]] = [
        (i, j, a - b)
        for i, a in enumerate(A)
        for j, b in enumerate(B)
    ]

    cand = {lo, hi}
    # Feasibility boundaries (c-T first feasible, c+T last feasible,
    # c+T+1 first infeasible) and residual kink (c) for each edge.
    for _i, _j, cv in edges:
        for d in (cv - tol, cv, cv + tol, cv + tol + 1):
            if lo <= d <= hi:
                cand.add(d)

    # Objective-3 optima: midpoint of the two residual extrema of some
    # matching, i.e. of two edges the matching can contain simultaneously.
    # Edges (i,j) and (i',j') co-occur only when their index order agrees;
    # at the midpoint both must lie inside tolerance, which requires
    # |c - c'| <= 2*tol.
    for x in range(len(edges)):
        i, j, c1 = edges[x]
        for y in range(x + 1, len(edges)):
            i2, j2, c2 = edges[y]
            if (i2 - i) * (j2 - j) <= 0:
                continue  # same index or an inversion -> never in one matching
            if c1 > c2:
                chi, clo = c1, c2
            else:
                chi, clo = c2, c1
            if chi - clo > 2 * tol:
                continue
            # Both edges' joint feasible window at the midpoint.
            flo = max(lo, chi - tol)
            fhi = min(hi, clo + tol)
            if flo > fhi:
                continue
            total = c1 + c2
            mid_floor = total // 2
            mid_ceil = -((-total) // 2)
            for md in (mid_floor, mid_ceil):
                d = md if flo <= md <= fhi else (flo if md < flo else fhi)
                if lo <= d <= hi:
                    cand.add(d)

    return sorted(cand)


@dataclass(frozen=True)
class Pair:
    index_a: int  # 1-based input index
    index_b: int
    a_time: int
    corrected_b: int  # b + offset
    residual: int  # signed: a - (b + offset)


@dataclass(frozen=True)
class Unpaired:
    index: int  # 1-based input index
    time: int


@dataclass(frozen=True)
class GapSegment:
    """Pulses skipped between two consecutive matched pairs.

    ``after_pair`` is the 1-based ordinal of the earlier matched pair; the
    skipped pulses are A indices ``(index_a_of_that_pair, index_a_of_next)``
    (exclusive on both ends), likewise for B.
    """

    after_pair: int
    skipped_a: int
    skipped_b: int
    a_indices: Tuple[int, ...]  # 1-based input indices of skipped pulses
    b_indices: Tuple[int, ...]

    def exceeds(self, ga: Optional[int], gb: Optional[int]) -> bool:
        return (ga is not None and self.skipped_a > ga) or (
            gb is not None and self.skipped_b > gb
        )

    def to_dict(self) -> dict:
        return {
            "after_pair": self.after_pair,
            "skipped_a": self.skipped_a,
            "skipped_b": self.skipped_b,
            "a_indices": list(self.a_indices),
            "b_indices": list(self.b_indices),
        }


@dataclass(frozen=True)
class CalibrationResult:
    offset: int
    pair_count: int
    residual_abs_sum: int
    max_abs_residual: int
    pairs: Tuple[Pair, ...]
    unpaired_a: Tuple[Unpaired, ...]
    unpaired_b: Tuple[Unpaired, ...]
    min_pairs: int
    sufficient: bool
    reason: Optional[str]
    gap_limit_enabled: bool = False
    max_gap_a: Optional[int] = None
    max_gap_b: Optional[int] = None
    # Skipped counts per segment between consecutive pairs of the winning
    # matching (empty when fewer than two pairs).
    gap_segments: Tuple[GapSegment, ...] = ()
    # Segments of the unconstrained optimum that violate the gap limits; the
    # constrained chain length that replaces them is reported separately.
    broken_segments: Tuple[GapSegment, ...] = ()

    def to_dict(self) -> dict:
        pairs = [
            {
                "index_a": p.index_a,
                "index_b": p.index_b,
                "a_time": p.a_time,
                "corrected_b": p.corrected_b,
                "residual": p.residual,
            }
            for p in self.pairs
        ]
        response = {
            "offset": self.offset,
            "pair_count": self.pair_count,
            "residual_abs_sum": self.residual_abs_sum,
            "max_abs_residual": self.max_abs_residual,
            "pairs": pairs,
            "unpaired_a": [
                {"index": u.index, "time": u.time} for u in self.unpaired_a
            ],
            "unpaired_b": [
                {"index": u.index, "time": u.time} for u in self.unpaired_b
            ],
            "min_pairs": self.min_pairs,
            "sufficient": self.sufficient,
            "reason": self.reason,
            "gap_limit_enabled": self.gap_limit_enabled,
            "max_gap_a": self.max_gap_a,
            "max_gap_b": self.max_gap_b,
            "gap_segments": [g.to_dict() for g in self.gap_segments],
        }
        if not self.sufficient:
            # No calibration value may be presented as a conclusion.  The best
            # count-aligned offset and its pairs survive only as an explicitly
            # labelled diagnostic, useful for explaining the shortfall.
            diag = {
                "note": "未达到最低配对数，以下偏移与配对仅为最大配对数对齐诊断，"
                        "不是校准结论。",
                "offset": self.offset,
                "residual_abs_sum": self.residual_abs_sum,
                "max_abs_residual": self.max_abs_residual,
                "pairs": pairs,
                "gap_segments": [g.to_dict() for g in self.gap_segments],
            }
            if self.gap_limit_enabled and self.broken_segments:
                diag["broken_segments"] = [
                    g.to_dict() for g in self.broken_segments
                ]
            response["offset"] = None
            response["pairs"] = []
            response["diagnostic"] = diag
            if self.gap_limit_enabled and self.broken_segments:
                response["broken_segments"] = [
                    g.to_dict() for g in self.broken_segments
                ]
        return response


def _gap_segments(
    pairs: Sequence[Tuple[int, int]]
) -> Tuple[GapSegment, ...]:
    """Skipped-pulse counts between consecutive matched pairs."""
    segs: List[GapSegment] = []
    for k in range(1, len(pairs)):
        pi, pj = pairs[k - 1]
        i, j = pairs[k]
        segs.append(
            GapSegment(
                after_pair=k,  # 1-based ordinal of the earlier pair
                skipped_a=i - pi - 1,
                skipped_b=j - pj - 1,
                a_indices=tuple(range(pi + 2, i + 1)),
                b_indices=tuple(range(pj + 2, j + 1)),
            )
        )
    return tuple(segs)


def solve(
    A: Sequence[int],
    B: Sequence[int],
    offset_min: int,
    offset_max: int,
    tolerance: int,
    min_pairs: int,
    gap_limit_enabled: bool = False,
    max_gap_a: Optional[int] = None,
    max_gap_b: Optional[int] = None,
) -> CalibrationResult:
    """Solve the joint offset / pairing problem exactly.

    When ``gap_limit_enabled`` is true, the consecutive-skipped-pulse limits
    are solved *jointly* with the integer offset and the order-preserving
    one-to-one matching: every candidate offset is evaluated by the chain DP
    directly, never by taking the unconstrained optimum and deleting breaks.

    Inputs are assumed to have been validated by the caller.
    """
    lo, hi = offset_min, offset_max

    def evaluate(d: int):
        if gap_limit_enabled:
            assert max_gap_a is not None and max_gap_b is not None
            return best_pairing_constrained(
                A, B, d, tolerance, max_gap_a, max_gap_b
            )
        c = _residual_matrix(A, B, d)
        return best_pairing_at(c, tolerance)

    # Global lexicographic record: (count, -cost, -max_abs, -offset)
    # maximised; the matching itself is re-derived canonically at the winning
    # offset so the index tie-break is applied at exactly that offset.
    best_score: Optional[Tuple[int, int, int, int]] = None
    best_offset = lo

    for d in _candidate_offsets(A, B, tolerance, lo, hi):
        obj, _pairs = evaluate(d)
        count, neg_cost, neg_max_abs, _key = obj

        score = (count, neg_cost, neg_max_abs, -d)
        if best_score is None or score > best_score:
            best_score = score
            best_offset = d

    assert best_score is not None

    # Re-derive the canonical matching at the winning offset.
    obj, pairs = evaluate(best_offset)

    pair_objs = tuple(
        Pair(
            index_a=i + 1,
            index_b=j + 1,
            a_time=A[i],
            corrected_b=B[j] + best_offset,
            residual=A[i] - (B[j] + best_offset),
        )
        for (i, j) in pairs
    )
    used_a = {i for (i, _) in pairs}
    used_b = {j for (_, j) in pairs}
    unpaired_a = tuple(
        Unpaired(index=i + 1, time=A[i])
        for i in range(len(A))
        if i not in used_a
    )
    unpaired_b = tuple(
        Unpaired(index=j + 1, time=B[j])
        for j in range(len(B))
        if j not in used_b
    )

    count = len(pairs)
    abs_sum = sum(abs(p.residual) for p in pair_objs)
    max_abs = max((abs(p.residual) for p in pair_objs), default=0)

    gap_segments = _gap_segments(pairs) if gap_limit_enabled else ()

    broken_segments: Tuple[GapSegment, ...] = ()
    if gap_limit_enabled:
        assert max_gap_a is not None and max_gap_b is not None
        sufficient = count >= min_pairs
        if sufficient:
            reason = None
        else:
            # Explain the shortfall with the unconstrained optimum's segments
            # that breach the limits: this is where the chain would break.
            # The unconstrained optimum is solved only here (the shortfall
            # path); it never takes part in the constrained decision, so this
            # is not a "take the optimum and cut it" pipeline.
            unc_score: Optional[Tuple[int, int, int, int]] = None
            unc_offset = lo
            for d in _candidate_offsets(A, B, tolerance, lo, hi):
                c = _residual_matrix(A, B, d)
                u_obj, _ = best_pairing_at(c, tolerance)
                u_score = (u_obj[0], u_obj[1], u_obj[2], -d)
                if unc_score is None or u_score > unc_score:
                    unc_score = u_score
                    unc_offset = d
            _, unc_pairs = best_pairing_at(
                _residual_matrix(A, B, unc_offset), tolerance
            )
            broken_segments = tuple(
                g
                for g in _gap_segments(unc_pairs)
                if g.exceeds(max_gap_a, max_gap_b)
            )
            limit_txt = (
                f"A 侧连续漏失上限 {max_gap_a}、B 侧 {max_gap_b}"
            )
            if broken_segments:
                detail = "；".join(
                    f"第 {g.after_pair} 对与第 {g.after_pair + 1} 对之间"
                    f"A 侧跳过 {g.skipped_a} 个、B 侧跳过 {g.skipped_b} 个脉冲"
                    for g in broken_segments
                )
                reason = (
                    f"启用{limit_txt}后，在偏移区间 [{offset_min}, {offset_max}]"
                    f" 纳秒、符合容差 ±{tolerance} 纳秒内，满足连续漏失约束的"
                    f"符合事件最多只有 {count} 对（要求至少 {min_pairs} 对）。"
                    f"无约束最优配对在以下区段越过漏失上限而发生断裂：{detail}；"
                    "首对之前与末对之后的脉冲不计入约束。"
                    "故不给出校准结论。"
                )
            else:
                reason = (
                    f"启用{limit_txt}后，在偏移区间 [{offset_min}, {offset_max}]"
                    f" 纳秒、符合容差 ±{tolerance} 纳秒内，满足连续漏失约束的"
                    f"符合事件最多只有 {count} 对（要求至少 {min_pairs} 对），"
                    "无法形成足够的符合事件，故不给出校准结论。"
                )
    else:
        sufficient = count >= min_pairs
        reason: Optional[str] = None
        if not sufficient:
            reason = (
                f"在偏移区间 [{offset_min}, {offset_max}] 纳秒、符合容差 "
                f"±{tolerance} 纳秒内，两台探头最多只能形成 {count} 对符合事件"
                f"（要求至少 {min_pairs} 对），无法形成足够的符合事件，"
                "故不给出校准结论。"
            )

    return CalibrationResult(
        offset=best_offset,
        pair_count=count,
        residual_abs_sum=abs_sum,
        max_abs_residual=max_abs,
        pairs=pair_objs,
        unpaired_a=unpaired_a,
        unpaired_b=unpaired_b,
        min_pairs=min_pairs,
        sufficient=sufficient,
        reason=reason,
        gap_limit_enabled=gap_limit_enabled,
        max_gap_a=max_gap_a if gap_limit_enabled else None,
        max_gap_b=max_gap_b if gap_limit_enabled else None,
        gap_segments=gap_segments,
        broken_segments=broken_segments,
    )
