"""HTTP/API tests run against the real server in a background thread."""

from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request
from urllib.request import Request

from app.server import build_server


class ServerHarness:
    def __init__(self):
        # Port 0 -> the OS assigns a free port.
        self.server = build_server(0)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def post(self, payload):
        data = json.dumps(payload).encode("utf-8")
        req = Request(
            f"http://127.0.0.1:{self.port}/api/calibrate",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def get(self, path):
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}{path}", timeout=10
            ) as resp:
                return resp.status, resp.read(), resp.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers


class ApiTests(unittest.TestCase):
    def test_healthz(self):
        with ServerHarness() as h:
            status, body, _ = h.get("/healthz")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body), {"status": "ok"})

    def test_index_served(self):
        with ServerHarness() as h:
            status, body, headers = h.get("/")
            self.assertEqual(status, 200)
            self.assertIn("text/html", headers["Content-Type"])
            self.assertIn("双探头".encode(), body)

    def test_calibrate_success_wide_interval(self):
        with ServerHarness() as h:
            shift = 424242424
            A = [1000 + k * 53 for k in range(8)]
            B = [a - shift for a in A]
            status, body = h.post({
                "probe_a": A,
                "probe_b": B,
                "offset_min": -1_000_000_000,
                "offset_max": 1_000_000_000,
                "tolerance": 5,
                "min_pairs": 6,
            })
            self.assertEqual(status, 200, body)
            self.assertTrue(body["sufficient"])
            self.assertEqual(body["offset"], shift)
            self.assertEqual(body["pair_count"], 8)
            for p in body["pairs"]:
                self.assertEqual(p["a_time"], p["corrected_b"])
                self.assertEqual(p["residual"], 0)
            self.assertEqual(body["unpaired_a"], [])
            self.assertEqual(body["unpaired_b"], [])

    def test_insufficient_reports_actual_count_no_fabrication(self):
        with ServerHarness() as h:
            status, body = h.post({
                "probe_a": [1, 2, 3, 4, 5, 6],
                "probe_b": [100, 102, 104, 106, 108, 110],
                "offset_min": -50,
                "offset_max": 50,
                "tolerance": 3,
                "min_pairs": 4,
            })
            self.assertEqual(status, 200)
            self.assertFalse(body["sufficient"])
            self.assertEqual(body["pair_count"], 0)
            self.assertIsNone(body["offset"])
            self.assertEqual(body["pairs"], [])
            self.assertIn("diagnostic", body)
            self.assertIn("无法形成足够的符合事件", body["reason"])
            self.assertIn("0", body["reason"])

    def test_boundary_min_pairs_exactly_met(self):
        with ServerHarness() as h:
            # Exactly 4 pairable, 2 noise pulses on each side.
            A = [10, 20, 30, 40, 1000, 1010]
            B = [10, 20, 30, 40, 2000, 2010]
            status, body = h.post({
                "probe_a": A, "probe_b": B,
                "offset_min": -5, "offset_max": 5,
                "tolerance": 0, "min_pairs": 4,
            })
            self.assertEqual(status, 200)
            self.assertTrue(body["sufficient"])
            self.assertEqual(body["pair_count"], 4)
            self.assertEqual(body["offset"], 0)

    def test_string_inputs_accepted(self):
        with ServerHarness() as h:
            status, body = h.post({
                "probe_a": "1, 2, 3, 4, 5, 6",
                "probe_b": "1 2 3 4 5 6",
                "offset_min": "-2",
                "offset_max": "2",
                "tolerance": "0",
                "min_pairs": "6",
            })
            self.assertEqual(status, 200, body)
            self.assertTrue(body["sufficient"])
            self.assertEqual(body["offset"], 0)

    def test_non_strictly_increasing_rejected(self):
        with ServerHarness() as h:
            status, body = h.post({
                "probe_a": [1, 2, 2, 4, 5, 6],
                "probe_b": [1, 2, 3, 4, 5, 6],
                "offset_min": 0, "offset_max": 0,
                "tolerance": 0, "min_pairs": 1,
            })
            self.assertEqual(status, 400)
            self.assertIn("严格递增", body["error"])
            self.assertEqual(body["field"], "probe_a")

    def test_wrong_pulse_count_rejected(self):
        with ServerHarness() as h:
            status, body = h.post({
                "probe_a": [1, 2, 3, 4, 5],
                "probe_b": [1, 2, 3, 4, 5, 6],
                "offset_min": 0, "offset_max": 0,
                "tolerance": 0, "min_pairs": 1,
            })
            self.assertEqual(status, 400)
            self.assertIn("6–24", body["error"])

    def test_bad_interval_rejected(self):
        with ServerHarness() as h:
            status, body = h.post({
                "probe_a": [1, 2, 3, 4, 5, 6],
                "probe_b": [1, 2, 3, 4, 5, 6],
                "offset_min": 10, "offset_max": 1,
                "tolerance": 0, "min_pairs": 1,
            })
            self.assertEqual(status, 400)
            self.assertIn("下限不能大于上限", body["error"])

    def test_non_integer_rejected(self):
        with ServerHarness() as h:
            status, body = h.post({
                "probe_a": [1, 2, 3, 4, 5, 6],
                "probe_b": [1, 2, 3, 4, 5, 6],
                "offset_min": 0.5, "offset_max": 1,
                "tolerance": 0, "min_pairs": 1,
            })
            self.assertEqual(status, 400)
            self.assertIn("整数", body["error"])

    def test_unknown_route(self):
        with ServerHarness() as h:
            status, _, _ = h.get("/nope")
            self.assertEqual(status, 404)

    # -- consecutive-miss cap ---------------------------------------------
    def _two_clusters_payload(self, **overrides):
        # Same fixture as CappedSolverTests: two coincidence clusters of 4,
        # 5 mutually unpairable noise pulses per side between them.
        c1 = [0, 10, 20, 30]
        noise_a = [60, 68, 76, 84, 92]
        c2 = [200, 210, 220, 230]
        A = c1 + noise_a + c2
        B = [x + 2 for x in c1] + [120, 128, 136, 144, 152] \
            + [x + 2 for x in c2]
        payload = {
            "probe_a": A,
            "probe_b": B,
            "offset_min": -10,
            "offset_max": 10,
            "tolerance": 3,
            "min_pairs": 7,
        }
        payload.update(overrides)
        return payload

    def test_gap_limit_disabled_is_backward_compatible(self):
        with ServerHarness() as h:
            # Explicitly disabled and omitted both behave like the original.
            for extra in ({}, {"gap_limit_enabled": False}):
                payload = self._two_clusters_payload(**extra)
                status, body = h.post(payload)
                self.assertEqual(status, 200, body)
                self.assertTrue(body["sufficient"])
                self.assertEqual(body["offset"], -2)
                self.assertEqual(body["pair_count"], 8)
                self.assertNotIn("gap_limits", body)
                self.assertNotIn("segments", body)

    def test_gap_limit_enabled_sufficient_shows_segments(self):
        with ServerHarness() as h:
            payload = self._two_clusters_payload(
                min_pairs=4,
                gap_limit_enabled=True,
                max_skipped_a=4,
                max_skipped_b=4,
            )
            status, body = h.post(payload)
            self.assertEqual(status, 200, body)
            self.assertTrue(body["sufficient"])
            self.assertEqual(body["offset"], -2)
            self.assertEqual(body["gap_limits"], {
                "enabled": True, "max_skipped_a": 4, "max_skipped_b": 4,
            })
            self.assertEqual(len(body["segments"]), 1)
            self.assertEqual(body["segments"][0]["pair_count"], 4)
            self.assertEqual(body["breaks"], [])

    def test_gap_limit_enabled_insufficient_reports_fracture(self):
        with ServerHarness() as h:
            payload = self._two_clusters_payload(
                gap_limit_enabled=True,
                max_skipped_a=4,
                max_skipped_b=4,
            )
            status, body = h.post(payload)
            self.assertEqual(status, 200, body)
            self.assertFalse(body["sufficient"])
            # No calibration offset on the page/API surface.
            self.assertIsNone(body["offset"])
            self.assertEqual(body["pairs"], [])
            self.assertEqual(body["pair_count"], 4)
            self.assertIn("连续漏失上限", body["reason"])
            diag = body["diagnostic"]
            fracture = diag["fracture"]
            self.assertEqual(fracture["pair_count"], 8)
            self.assertEqual(
                [s["pair_count"] for s in fracture["segments"]], [4, 4]
            )
            br = fracture["breaks"][0]
            self.assertEqual(br["skipped_a"], 5)
            self.assertEqual(br["skipped_b"], 5)
            self.assertTrue(br["a_exceeded"] and br["b_exceeded"])

    def test_gap_limit_zero_accepted(self):
        with ServerHarness() as h:
            payload = self._two_clusters_payload(
                min_pairs=1,
                gap_limit_enabled=True,
                max_skipped_a=0,
                max_skipped_b=0,
            )
            status, body = h.post(payload)
            self.assertEqual(status, 200, body)
            self.assertEqual(
                body["gap_limits"]["max_skipped_a"], 0
            )

    def test_gap_limit_enabled_requires_both_limits(self):
        with ServerHarness() as h:
            payload = self._two_clusters_payload(
                gap_limit_enabled=True, max_skipped_a=2,
            )
            status, body = h.post(payload)
            self.assertEqual(status, 400)
            self.assertEqual(body["field"], "max_skipped_b")

    def test_negative_gap_limit_rejected(self):
        with ServerHarness() as h:
            payload = self._two_clusters_payload(
                gap_limit_enabled=True,
                max_skipped_a=-1,
                max_skipped_b=2,
            )
            status, body = h.post(payload)
            self.assertEqual(status, 400)
            self.assertIn("不能为负", body["error"])
            self.assertEqual(body["field"], "max_skipped_a")

    def test_string_gap_limit_inputs_accepted(self):
        with ServerHarness() as h:
            payload = self._two_clusters_payload(
                min_pairs=4,
                gap_limit_enabled="true",
                max_skipped_a="4",
                max_skipped_b="4",
            )
            status, body = h.post(payload)
            self.assertEqual(status, 200, body)
            self.assertTrue(body["sufficient"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
