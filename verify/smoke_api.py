"""Wide-offset-interval API smoke test for the one-shot verify service."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

BASE_URL = os.environ.get("APP_BASE_URL", "http://app:8080").rstrip("/")


def request(method: str, path: str, payload=None):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(
        BASE_URL + path, data=data, headers=headers, method=method
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def check(cond: bool, message: str) -> None:
    if not cond:
        print(f"SMOKE FAIL: {message}", file=sys.stderr)
        raise SystemExit(1)
    print(f"  ok: {message}")


def main() -> int:
    print(f"target: {BASE_URL}")

    status, body = request("GET", "/healthz")
    check(status == 200 and body.get("status") == "ok", "health check is ok")

    # Wide 2,000,000,000 ns interval; the true shift is a large nonzero
    # integer that a nanosecond scan could never reach in time.
    shift = -765_432_198
    A = [10**12 + k * 137 + (k % 3) for k in range(10)]
    B = [a - shift for a in A]
    payload = {
        "probe_a": A,
        "probe_b": B,
        "offset_min": -1_000_000_000,
        "offset_max": 1_000_000_000,
        "tolerance": 3,
        "min_pairs": 8,
    }
    status, body = request("POST", "/api/calibrate", payload)
    check(status == 200, f"wide-interval calibrate HTTP 200 (got {status})")
    check(body.get("sufficient") is True, "wide-interval result sufficient")
    check(body.get("offset") == shift, f"exact offset recovered ({shift})")
    check(body.get("pair_count") == 10, "all 10 pulses paired")
    check(body.get("residual_abs_sum") == 0, "residual abs sum is 0")
    check(body.get("max_abs_residual") == 0, "max abs residual is 0")
    check(len(body.get("pairs", [])) == 10, "10 pair records returned")
    for p in body["pairs"]:
        check(
            p["corrected_b"] == p["a_time"] and p["residual"] == 0,
            f"pair A#{p['index_a']} corrected time matches",
        )

    # Insufficient coincidences: B is ~2e9 ns away from A, outside the whole
    # +/-1e9 offset interval, so zero pairs are possible. The API must report
    # the real maximum count and a reason, and must not present an offset as
    # calibration.
    bad = {
        "probe_a": [1, 2, 3, 4, 5, 6],
        "probe_b": [2_000_000_000 + k * 10 for k in range(6)],
        "offset_min": -1_000_000_000,
        "offset_max": 1_000_000_000,
        "tolerance": 5,
        "min_pairs": 4,
    }
    status, body = request("POST", "/api/calibrate", bad)
    check(status == 200, "insufficient case HTTP 200")
    check(body.get("sufficient") is False, "insufficient flag set")
    check(body.get("pair_count") == 0, "actual maximum pair count reported (0)")
    check(body.get("offset") is None, "no fabricated calibration offset")
    check(body.get("pairs") == [], "no pairs presented as a calibration")
    check(bool(body.get("reason")), "reason for shortfall provided")
    check(
        "diagnostic" in body and "offset" in body["diagnostic"],
        "diagnostic alignment kept separate",
    )

    # Validation error path.
    bad_input = dict(bad)
    bad_input["probe_a"] = [1, 2, 2, 4, 5, 6]
    status, body = request("POST", "/api/calibrate", bad_input)
    check(status == 400, "non-strict input rejected with 400")
    check("严格递增" in body.get("error", ""), "validation message returned")

    # ---- consecutive-miss cap: DISABLED (compatibility) ----------------
    # Scattered coincidences: two tight clusters of 4 with 5 mutually
    # unpairable noise pulses per side between them.  Without the cap the
    # pair-count-first rule joins all 8 pairs across the big gap, exactly as
    # before the feature existed.
    c1 = [0, 10, 20, 30]
    noise_a = [60, 68, 76, 84, 92]
    c2 = [200, 210, 220, 230]
    scattered_a = c1 + noise_a + c2
    scattered_b = [x + 2 for x in c1] + [120, 128, 136, 144, 152] \
        + [x + 2 for x in c2]
    scattered = {
        "probe_a": scattered_a,
        "probe_b": scattered_b,
        "offset_min": -10,
        "offset_max": 10,
        "tolerance": 3,
        "min_pairs": 7,
    }
    status, body = request("POST", "/api/calibrate", scattered)
    check(status == 200, "scattered case HTTP 200")
    check(body.get("sufficient") is True, "cap disabled: scattered 8 pairs suffice")
    check(body.get("pair_count") == 8, "cap disabled: 8 pairs reported")
    check(body.get("offset") == -2, "cap disabled: offset -2 recovered")
    check("gap_limits" not in body, "cap disabled: no gap_limits field")
    check("segments" not in body, "cap disabled: no segments field")

    # Same request with the cap explicitly enabled and tight limits: the
    # scattered join crosses 5 skipped pulses per side, so it must be
    # rejected.  The joint constrained optimum has 4 pairs < threshold 7,
    # hence no offset; the fracture section must name the 5/5 gap.
    enabled = dict(
        scattered,
        gap_limit_enabled=True,
        max_skipped_a=4,
        max_skipped_b=4,
    )
    status, body = request("POST", "/api/calibrate", enabled)
    check(status == 200, "cap enabled: HTTP 200")
    check(body.get("sufficient") is False, "cap enabled: result insufficient")
    check(body.get("pair_count") == 4, "cap enabled: real constrained max is 4")
    check(body.get("offset") is None, "cap enabled: no fabricated offset")
    check(body.get("pairs") == [], "cap enabled: no pairs as conclusion")
    check(
        body.get("gap_limits") == {
            "enabled": True, "max_skipped_a": 4, "max_skipped_b": 4,
        },
        "cap enabled: limits echoed back",
    )
    diag = body.get("diagnostic", {})
    fracture = diag.get("fracture")
    check(fracture is not None, "cap enabled: fracture diagnostic present")
    if fracture:
        check(fracture.get("pair_count") == 8, "fracture shows 8 unconstrained pairs")
        check(
            [s.get("pair_count") for s in fracture.get("segments", [])] == [4, 4],
            "fracture splits alignment into two 4-pair segments",
        )
        breaks = fracture.get("breaks", [])
        check(len(breaks) == 1, "exactly one breaking miss section")
        if breaks:
            br = breaks[0]
            check(br.get("skipped_a") == 5, "fracture gap skipped_a == 5")
            check(br.get("skipped_b") == 5, "fracture gap skipped_b == 5")
            check(br.get("a_exceeded") is True, "A side marked exceeded")
            check(br.get("b_exceeded") is True, "B side marked exceeded")
    check("断裂" in body.get("reason", ""), "reason names the fracture")
    # The capped answer is itself shown per-segment (one chain, one segment).
    check(
        [s.get("pair_count") for s in diag.get("segments", [])] == [4],
        "constrained answer reported as one cap-respecting segment",
    )

    # Enabled but loose caps: the join is allowed and calibration stands.
    loose = dict(
        scattered,
        min_pairs=8,
        gap_limit_enabled=True,
        max_skipped_a=5,
        max_skipped_b=5,
    )
    status, body = request("POST", "/api/calibrate", loose)
    check(status == 200, "loose cap HTTP 200")
    check(body.get("sufficient") is True, "loose cap: sufficient")
    check(body.get("offset") == -2, "loose cap: offset given")
    check(body.get("pair_count") == 8, "loose cap: 8 pairs")
    check(len(body.get("segments", [])) == 1, "loose cap: one segment")
    check(body.get("breaks") == [], "loose cap: no breaks")

    # Enabled with invalid (missing / negative) limits -> 400.
    missing = dict(scattered, gap_limit_enabled=True, max_skipped_a=1)
    status, body = request("POST", "/api/calibrate", missing)
    check(status == 400, "missing B cap rejected")
    negative = dict(
        scattered, gap_limit_enabled=True,
        max_skipped_a=-1, max_skipped_b=2,
    )
    status, body = request("POST", "/api/calibrate", negative)
    check(status == 400, "negative cap rejected")

    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
