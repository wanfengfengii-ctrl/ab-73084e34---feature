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
of candidate offsets and run a matching DP once per candidate:

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

Optional "consecutive-miss cap" mode (``max_skipped_a`` / ``max_skipped_b``)
---------------------------------------------------------------------------

When enabled, between two *consecutive* paired events (i,j) and (i',j') the
number of skipped A pulses (i' - i - 1) and skipped B pulses (j' - j - 1)
must each stay within its own cap.  Pulses before the first pair and after
the last pair are not constrained.  The caps are solved **jointly** with the
offset and the pairing: for each candidate offset we run a DAG longest-path
DP over admissible edges, where an edge may follow another only through the
allowed index rectangle (the caps), using sliding-window maxima so the DP is
still O(n*m) per offset.  The *same* finite candidate set suffices: the
capped chain structure depends only on which edges are feasible at the
offset (the feasible-edge set changes only at single-edge window boundaries
c_ij +/- T, already in the set), and the residual kink / extrema-midpoint
arguments apply verbatim to any fixed feasible chain.  The result is
segmented at every gap that breaks a cap; segments and breaks carry the
per-side skipped counts.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional, Sequence, Tuple

# A pairing's lexicographic objective used *inside* the DP, maximised:
#   (pair_count, -abs_sum, -max_abs_residual, index_key)
# ``max`` on this tuple implements: more pairs, smaller abs sum, smaller
# largest absolute residual, then lexicographically smallest paired indices.
Objective = Tuple[int, int, int, Tuple[Tuple[int, int], ...]]

_EMPTY_OBJECTIVE: Objective = (0, 0, 0, ())


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


def constrained_pairing_at(
    c: Sequence[Sequence[int]],
    tol: int,
    max_skip_a: int,
    max_skip_b: int,
) -> Tuple[Objective, List[Tuple[int, int]]]:
    """Optimal order-preserving matching under the consecutive-miss caps.

    A chain of admissible edges (pairs) must satisfy, between every two
    consecutive edges (i,j) -> (i',j'):

        i' - i - 1 <= max_skip_a     (skipped A pulses)
        j' - j - 1 <= max_skip_b     (skipped B pulses)

    Pulses before the first / after the last pair are unrestricted, so any
    admissible edge may start or end a chain.

    The recurrence is a DAG longest-path over admissible edges ordered by
    input index: the best predecessor of edge (i,j) is the best chain ending
    at an edge of the index rectangle
    [i-1-max_skip_a, i-1] x [j-1-max_skip_b, j-1].  Its maximum is found
    with two nested sliding-window maxima (per-column deques over the row
    window, then a per-row deque over the column window), making the DP
    O(n*m) for one offset.  Objectives are the same tuple as in the
    unconstrained DP; appending one edge is monotone in the predecessor
    objective, so the rectangle maximum is exactly the best predecessor.
    """
    n = len(c)
    m = len(c[0]) if n else 0

    # values[i][j]: best objective of a valid chain ending exactly at edge
    # (i, j); None when (i, j) is not part of any chain (incl. infeasible).
    values: List[List[Optional[Objective]]] = [
        [None] * m for _ in range(n)
    ]
    # parents[i][j]: predecessor edge (pi, pj), or None when the chain
    # starts at (i, j).
    parents: List[List[Optional[Tuple[int, int]]]] = [
        [None] * m for _ in range(n)
    ]

    # One monotonic deque per B column: rows of the sliding row window,
    # front holding the row with the largest chain objective in that column.
    col_deq: List[Deque[int]] = [deque() for _ in range(m)]
    best_end: Optional[Tuple[Objective, int, int]] = None

    for i in range(n):
        # Row i-1 has just been completed; admit it into the column deques.
        if i > 0:
            r = i - 1
            for jc in range(m):
                v = values[r][jc]
                if v is None:
                    continue
                dq = col_deq[jc]
                while dq and values[dq[-1]][jc] <= v:  # type: ignore[operator]
                    dq.pop()
                dq.append(r)
        # Evict rows that are now too far behind: i - r - 1 > max_skip_a.
        low_row = i - 1 - max_skip_a
        for dq in col_deq:
            while dq and dq[0] < low_row:
                dq.popleft()

        # Horizontal sliding maximum over columns of the row window; entries
        # are (objective, predecessor row, predecessor column), appended in
        # increasing column order.
        hdeq: Deque[Tuple[Objective, int, int]] = deque()
        for j in range(m):
            if j > 0:
                jc = j - 1
                dq = col_deq[jc]
                if dq:
                    pr = dq[0]
                    pv = values[pr][jc]
                    assert pv is not None
                    while hdeq and hdeq[-1][0] <= pv:
                        hdeq.pop()
                    hdeq.append((pv, pr, jc))
            low_col = j - 1 - max_skip_b
            while hdeq and hdeq[0][2] < low_col:
                hdeq.popleft()

            e = c[i][j]
            if -tol <= e <= tol:
                if hdeq:
                    pobj, pi, pj = hdeq[0]
                    parent: Optional[Tuple[int, int]] = (pi, pj)
                else:
                    # Chain starts here: the unmatched prefix is free.
                    pobj = _EMPTY_OBJECTIVE
                    parent = None
                ae = e if e >= 0 else -e
                cand: Objective = (
                    pobj[0] + 1,
                    pobj[1] - ae,
                    min(pobj[2], -ae),
                    pobj[3] + ((i, j),),
                )
                values[i][j] = cand
                parents[i][j] = parent
                if best_end is None or cand > best_end[0]:
                    best_end = (cand, i, j)

    if best_end is None:
        return _empty_objective(), []

    final, i, j = best_end
    pairs: List[Tuple[int, int]] = []
    while True:
        pairs.append((i, j))
        prev = parents[i][j]
        if prev is None:
            break
        i, j = prev
    pairs.reverse()
    return final, pairs


def _residual_matrix(A: Sequence[int], B: Sequence[int], offset: int):
    return [[a - b - offset for b in B] for a in A]


def _raw_edges(
    A: Sequence[int], B: Sequence[int]
) -> List[Tuple[int, int, int]]:
    return [
        (i, j, a - b)
        for i, a in enumerate(A)
        for j, b in enumerate(B)
    ]


def _candidate_offsets(
    A: Sequence[int], B: Sequence[int], tol: int, lo: int, hi: int
) -> List[int]:
    """Finite, provably sufficient set of offsets to evaluate.

    See the module docstring for why the global optimum must lie in this set.
    """
    edges = _raw_edges(A, B)

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
    segment: Optional[int] = None  # 1-based capped-chain segment, if enabled


@dataclass(frozen=True)
class Unpaired:
    index: int  # 1-based input index
    time: int


@dataclass(frozen=True)
class Gap:
    """Gap between two consecutive paired events (indices are 1-based)."""

    after_index_a: int
    after_index_b: int
    before_index_a: int
    before_index_b: int
    skipped_a: int
    skipped_b: int
    a_within_limit: bool
    b_within_limit: bool

    @property
    def is_break(self) -> bool:
        return not (self.a_within_limit and self.b_within_limit)

    def to_dict(self) -> dict:
        return {
            "after_index_a": self.after_index_a,
            "after_index_b": self.after_index_b,
            "before_index_a": self.before_index_a,
            "before_index_b": self.before_index_b,
            "skipped_a": self.skipped_a,
            "skipped_b": self.skipped_b,
            "a_within_limit": self.a_within_limit,
            "b_within_limit": self.b_within_limit,
        }

    def describe(self) -> str:
        sides = []
        if not self.a_within_limit:
            sides.append(f"A 侧跳过 {self.skipped_a} 个")
        if not self.b_within_limit:
            sides.append(f"B 侧跳过 {self.skipped_b} 个")
        return (
            f"A#{self.after_index_a}→A#{self.before_index_a} 与 "
            f"B#{self.after_index_b}→B#{self.before_index_b} 之间"
            + ("（" + "、".join(sides) + "越限）" if sides else "")
        )


@dataclass(frozen=True)
class Segment:
    """One maximal run of pairs in which every gap respects both caps."""

    segment: int  # 1-based
    pair_count: int
    first_index_a: int
    last_index_a: int
    first_index_b: int
    last_index_b: int
    internal_skipped_a: int
    internal_skipped_b: int
    gaps: Tuple[Gap, ...]

    def to_dict(self) -> dict:
        return {
            "segment": self.segment,
            "pair_count": self.pair_count,
            "first_index_a": self.first_index_a,
            "last_index_a": self.last_index_a,
            "first_index_b": self.first_index_b,
            "last_index_b": self.last_index_b,
            "internal_skipped_a": self.internal_skipped_a,
            "internal_skipped_b": self.internal_skipped_b,
            "gaps": [g.to_dict() for g in self.gaps],
        }


@dataclass(frozen=True)
class Break:
    """Gap between two segments: at least one side exceeded its cap."""

    after_segment: int
    before_segment: int
    gap: Gap
    limit_a: int
    limit_b: int

    def to_dict(self) -> dict:
        d = self.gap.to_dict()
        d.update(
            {
                "after_segment": self.after_segment,
                "before_segment": self.before_segment,
                "limit_a": self.limit_a,
                "limit_b": self.limit_b,
                "a_exceeded": not self.gap.a_within_limit,
                "b_exceeded": not self.gap.b_within_limit,
            }
        )
        return d


def _build_segments(
    pairs: Sequence[Tuple[int, int]],
    max_skip_a: int,
    max_skip_b: int,
) -> Tuple[Tuple[Segment, ...], Tuple[Break, ...]]:
    """Split the optimal capped pairing into segments and breaks.

    Only gaps *between consecutive pairs* are inspected: unmatched pulses
    before the first pair or after the last pair do not exist as gaps here
    and therefore never constrain anything.
    """
    segments: List[Segment] = []
    breaks: List[Break] = []
    if not pairs:
        return (), ()

    start = 0
    gaps: List[Gap] = []
    segment_no = 0

    def close(end: int, gaps: List[Gap]) -> None:
        nonlocal segment_no
        segment_no += 1
        fi, fj = pairs[start]
        li, lj = pairs[end - 1]
        segments.append(
            Segment(
                segment=segment_no,
                pair_count=end - start,
                first_index_a=fi + 1,
                last_index_a=li + 1,
                first_index_b=fj + 1,
                last_index_b=lj + 1,
                internal_skipped_a=sum(g.skipped_a for g in gaps),
                internal_skipped_b=sum(g.skipped_b for g in gaps),
                gaps=tuple(gaps),
            )
        )

    for t in range(1, len(pairs)):
        (i1, j1), (i2, j2) = pairs[t - 1], pairs[t]
        sa, sb = i2 - i1 - 1, j2 - j1 - 1
        a_ok = sa <= max_skip_a
        b_ok = sb <= max_skip_b
        gap = Gap(
            after_index_a=i1 + 1,
            after_index_b=j1 + 1,
            before_index_a=i2 + 1,
            before_index_b=j2 + 1,
            skipped_a=sa,
            skipped_b=sb,
            a_within_limit=a_ok,
            b_within_limit=b_ok,
        )
        if gap.is_break:
            close(t, gaps)
            breaks.append(
                Break(
                    after_segment=segment_no,
                    before_segment=segment_no + 1,
                    gap=gap,
                    limit_a=max_skip_a,
                    limit_b=max_skip_b,
                )
            )
            start = t
            gaps = []
        else:
            gaps.append(gap)

    close(len(pairs), gaps)
    return tuple(segments), tuple(breaks)


@dataclass(frozen=True)
class FractureDiagnostic:
    """Diagnostic-only view in capped mode: the unconstrained best alignment
    segmented by the caps, showing where the cap cuts a longer alignment.

    Never presented as a calibration conclusion and never used to derive the
    (constrained) answer.
    """

    offset: int
    pair_count: int
    residual_abs_sum: int
    max_abs_residual: int
    pairs: Tuple[Pair, ...]
    segments: Tuple[Segment, ...]
    breaks: Tuple[Break, ...]

    def to_dict(self) -> dict:
        out = []
        for p in self.pairs:
            d = {
                "index_a": p.index_a,
                "index_b": p.index_b,
                "a_time": p.a_time,
                "corrected_b": p.corrected_b,
                "residual": p.residual,
            }
            if p.segment is not None:
                d["segment"] = p.segment
            out.append(d)
        return {
            "offset": self.offset,
            "pair_count": self.pair_count,
            "residual_abs_sum": self.residual_abs_sum,
            "max_abs_residual": self.max_abs_residual,
            "pairs": out,
            "segments": [s.to_dict() for s in self.segments],
            "breaks": [b.to_dict() for b in self.breaks],
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
    max_skipped_a: Optional[int] = None
    max_skipped_b: Optional[int] = None
    segments: Tuple[Segment, ...] = field(default=())
    breaks: Tuple[Break, ...] = field(default=())
    fracture: Optional[FractureDiagnostic] = None

    def to_dict(self) -> dict:
        def pair_dicts(pair_seq: Sequence[Pair]) -> List[dict]:
            out = []
            for p in pair_seq:
                d = {
                    "index_a": p.index_a,
                    "index_b": p.index_b,
                    "a_time": p.a_time,
                    "corrected_b": p.corrected_b,
                    "residual": p.residual,
                }
                if p.segment is not None:
                    d["segment"] = p.segment
                out.append(d)
            return out

        pairs = pair_dicts(self.pairs)
        response: Dict[str, object] = {
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
        }
        if self.gap_limit_enabled:
            response["gap_limits"] = {
                "enabled": True,
                "max_skipped_a": self.max_skipped_a,
                "max_skipped_b": self.max_skipped_b,
            }
            response["segments"] = [s.to_dict() for s in self.segments]
            response["breaks"] = [b.to_dict() for b in self.breaks]
        if not self.sufficient:
            # No calibration value may be presented as a conclusion.  The best
            # count-aligned offset and its pairs survive only as an explicitly
            # labelled diagnostic, useful for explaining the shortfall.
            diagnostic: Dict[str, object] = {
                "note": "未达到最低配对数，以下偏移与配对仅为最大配对数对齐诊断，"
                        "不是校准结论。",
                "offset": self.offset,
                "residual_abs_sum": self.residual_abs_sum,
                "max_abs_residual": self.max_abs_residual,
                "pairs": pairs,
            }
            if self.gap_limit_enabled:
                diagnostic["gap_limits"] = response["gap_limits"]
                # The capped answer is one cap-respecting chain; the fracture
                # view shows where those caps cut the unconstrained alignment.
                diagnostic["segments"] = response["segments"]
                diagnostic["breaks"] = response["breaks"]
                if self.fracture is not None:
                    diagnostic["fracture"] = self.fracture.to_dict()
            response["offset"] = None
            response["pairs"] = []
            response["diagnostic"] = diagnostic
        return response


def solve(
    A: Sequence[int],
    B: Sequence[int],
    offset_min: int,
    offset_max: int,
    tolerance: int,
    min_pairs: int,
    max_skipped_a: Optional[int] = None,
    max_skipped_b: Optional[int] = None,
) -> CalibrationResult:
    """Solve the joint offset / pairing problem exactly.

    Inputs are assumed to have been validated by the caller.  When both
    ``max_skipped_*`` are None the problem is the original unconstrained
    one; otherwise the consecutive-miss caps are part of the same joint
    optimisation (never applied by trimming an unconstrained optimum).
    """
    lo, hi = offset_min, offset_max
    capped = max_skipped_a is not None and max_skipped_b is not None

    # Global lexicographic record: (count, -cost, -max_abs, -offset)
    # maximised; the matching itself is re-derived canonically at the winning
    # offset so the index tie-break is applied at exactly that offset.
    best_score: Optional[Tuple[int, int, int, int]] = None
    best_offset = lo

    if capped:
        assert max_skipped_a is not None and max_skipped_b is not None
    candidates = _candidate_offsets(A, B, tolerance, lo, hi)

    for d in candidates:
        c = [[a - b - d for b in B] for a in A]
        if capped:
            obj, _pairs = constrained_pairing_at(
                c, tolerance, max_skipped_a, max_skipped_b
            )
        else:
            obj, _pairs = best_pairing_at(c, tolerance)
        count, neg_cost, neg_max_abs, _key = obj

        score = (count, neg_cost, neg_max_abs, -d)
        if best_score is None or score > best_score:
            best_score = score
            best_offset = d

    assert best_score is not None

    # Diagnostic-only data for capped insufficiency: the unconstrained
    # optimum, computed lazily *after* the capped answer is known.  It is
    # used solely to point at the miss gaps where the cap cuts a longer
    # alignment; it never determines the answer (the capped record above
    # does), so this is not "optimise then trim".
    unc_offset = lo
    if capped and best_score[0] < min_pairs:
        unc_score: Optional[Tuple[int, int, int, int]] = None
        for d in _candidate_offsets(A, B, tolerance, lo, hi):
            c = [[a - b - d for b in B] for a in A]
            uobj, _upairs = best_pairing_at(c, tolerance)
            uscore = (uobj[0], uobj[1], uobj[2], -d)
            if unc_score is None or uscore > unc_score:
                unc_score = uscore
                unc_offset = d

    # Re-derive the canonical matching at the winning offset.
    c = _residual_matrix(A, B, best_offset)
    fracture: Optional[FractureDiagnostic] = None
    if capped:
        _obj, raw_pairs = constrained_pairing_at(
            c, tolerance, max_skipped_a, max_skipped_b
        )
        # The joint capped optimum is, by construction of the chain DP, one
        # cap-respecting chain: every gap between consecutive pairs lies in
        # both caps.  It is therefore a single segment whose internal gaps
        # carry the per-side skipped counts for display.
        segments, answer_breaks = _build_segments(
            raw_pairs, max_skipped_a, max_skipped_b
        )
        assert not answer_breaks, "capped optimum must not contain a break"
        breaks = ()
        segment_of = {pair: 1 for pair in raw_pairs}

        # Fracture diagnostic only: segment the *unconstrained* optimum under
        # the same caps to expose the miss sections that stop a longer chain.
        if best_score[0] < min_pairs:
            uc = _residual_matrix(A, B, unc_offset)
            _uobj, unc_pairs = best_pairing_at(uc, tolerance)
            if unc_pairs:
                f_segments, f_breaks = _build_segments(
                    unc_pairs, max_skipped_a, max_skipped_b
                )
                f_segment_of: Dict[Tuple[int, int], int] = {}
                ordinal = 0
                for seg in f_segments:
                    for _ in range(seg.pair_count):
                        f_segment_of[unc_pairs[ordinal]] = seg.segment
                        ordinal += 1
                f_pair_objs = tuple(
                    Pair(
                        index_a=i + 1,
                        index_b=j + 1,
                        a_time=A[i],
                        corrected_b=B[j] + unc_offset,
                        residual=A[i] - (B[j] + unc_offset),
                        segment=f_segment_of.get((i, j)),
                    )
                    for (i, j) in unc_pairs
                )
                fracture = FractureDiagnostic(
                    offset=unc_offset,
                    pair_count=len(unc_pairs),
                    residual_abs_sum=sum(
                        abs(p.residual) for p in f_pair_objs
                    ),
                    max_abs_residual=max(
                        (abs(p.residual) for p in f_pair_objs), default=0
                    ),
                    pairs=f_pair_objs,
                    segments=f_segments,
                    breaks=f_breaks,
                )
    else:
        _obj, raw_pairs = best_pairing_at(c, tolerance)
        segments, breaks = (), ()
        segment_of = {}

    pair_objs = tuple(
        Pair(
            index_a=i + 1,
            index_b=j + 1,
            a_time=A[i],
            corrected_b=B[j] + best_offset,
            residual=A[i] - (B[j] + best_offset),
            segment=segment_of.get((i, j)),
        )
        for (i, j) in raw_pairs
    )
    used_a = {i for (i, _) in raw_pairs}
    used_b = {j for (_, j) in raw_pairs}
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

    count = len(raw_pairs)
    abs_sum = sum(abs(p.residual) for p in pair_objs)
    max_abs = max((abs(p.residual) for p in pair_objs), default=0)

    sufficient = count >= min_pairs
    reason: Optional[str] = None
    if not sufficient:
        if capped:
            break_text = ""
            if fracture is not None and fracture.breaks:
                details = "；".join(
                    f"第 {b.after_segment} 段与第 {b.before_segment} 段之间"
                    f"（{b.gap.describe()}）"
                    for b in fracture.breaks
                )
                break_text = f" 不受限最优对齐（{fracture.pair_count} 对）" \
                    f"在以下漏失区段断裂：{details}。"
            reason = (
                f"在偏移区间 [{offset_min}, {offset_max}] 纳秒、符合容差 "
                f"±{tolerance} 纳秒、连续漏失上限（A 侧 {max_skipped_a} 个、"
                f"B 侧 {max_skipped_b} 个）约束下，两台探头最多只能形成 "
                f"{count} 对符合事件（要求至少 {min_pairs} 对），"
                f"无法形成足够的符合事件，故不给出校准结论。{break_text}"
            )
        else:
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
        gap_limit_enabled=capped,
        max_skipped_a=max_skipped_a if capped else None,
        max_skipped_b=max_skipped_b if capped else None,
        segments=segments,
        breaks=breaks,
        fracture=fracture,
    )
