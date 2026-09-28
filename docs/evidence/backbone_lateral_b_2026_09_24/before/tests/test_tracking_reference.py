"""Pure checks for the frozen analytic tracking references and geometry."""
import copy
import math
import sys
import unittest
from pathlib import Path

import numpy as np
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from planning.tracking_reference import (
    CASES,
    actor_target,
    body_polygon,
    case_spec,
    clearance,
    corridor,
    generate_reference,
    state_at,
    validate_reference,
)


GEOMETRY = {
    "front": 3.848486,
    "rear": 1.053197,
    "width": 2.128324,
    "box_center_y": 0.0,
    "box_yaw": 0.0,
}


class TrackingReferenceTests(unittest.TestCase):
    def test_case_contract_is_complete_and_json_shaped(self):
        self.assertEqual(CASES, ["S2", "L2", "R2", "SR2", "S4", "L4", "R4", "SR4"])
        expected = {"S2": 15, "L2": 27, "R2": 27, "SR2": 30,
                    "S4": 21, "L4": 27, "R4": 27, "SR4": 42}
        for name, duration in expected.items():
            spec = case_spec(name)
            self.assertEqual(set(spec), {"name", "V", "duration", "segments", "stops", "accels", "turn_end"})
            self.assertEqual(spec["duration"], float(duration))
            self.assertEqual(spec["V"], float(name[-1]))
            self.assertEqual(spec["segments"][0]["start"], 0.0)
            self.assertEqual(spec["segments"][-1]["end"], float(duration))
            self.assertTrue(all(set(segment) == {"kind", "start", "end", "v0", "v1", "turn"}
                                for segment in spec["segments"]))
            self.assertEqual(spec["stops"], [
                {"start": segment["start"], "end": segment["end"]}
                for segment in spec["segments"] if segment["kind"] == "H"
            ])
            self.assertEqual(spec["accels"], [
                {key: segment[key] for key in ("start", "end", "v0", "v1")}
                for segment in spec["segments"] if segment["kind"] == "A"
            ])
        self.assertIsNone(case_spec("S2")["turn_end"])
        self.assertEqual(case_spec("L4")["turn_end"], 16.0)
        with self.assertRaises(ValueError):
            case_spec("unknown")

    def test_reference_uses_exact_ticks_and_static_extension(self):
        reference = generate_reference("S2")
        self.assertEqual(len(reference), 15 * 10 + 5)
        self.assertEqual(reference[0]["t"], 0.0)
        self.assertEqual(reference[-1]["t"], 15.4)
        self.assertEqual(set(reference[0]), {"t", "x", "y", "yaw", "v", "a", "jerk", "kappa", "kappa_rate"})
        self.assertTrue(all(np.isfinite(list(row.values())).all() for row in reference))
        self.assertAlmostEqual(state_at(reference, 15.0)["x"], 16.0, places=9)
        for row in reference[-5:]:
            self.assertEqual((row["v"], row["a"], row["jerk"], row["kappa"], row["kappa_rate"]),
                             (0.0, 0.0, 0.0, 0.0, 0.0))
        with self.assertRaises(ValueError):
            state_at(reference, 0.15)
        with self.assertRaises(ValueError):
            state_at(reference, 15.5)

    def test_profiles_obey_frozen_bounds_and_left_right_are_mirrors(self):
        for speed, case, jerk_bound in ((2.0, "L2", 0.721688), (4.0, "L4", 0.360844)):
            reference = generate_reference(case)
            self.assertLessEqual(max(abs(row["a"]) for row in reference), 0.9375 + 1e-12)
            self.assertLessEqual(max(abs(row["jerk"]) for row in reference), jerk_bound + 1e-5)
            self.assertLessEqual(max(abs(row["kappa_rate"]) for row in reference),
                                 0.01171875 * speed + 1e-12)
        left, right = generate_reference("L4"), generate_reference("R4")
        for lhs, rhs in zip(left, right):
            self.assertAlmostEqual(lhs["x"], rhs["x"], places=9)
            self.assertAlmostEqual(lhs["y"], -rhs["y"], places=9)
            self.assertAlmostEqual(lhs["yaw"], -rhs["yaw"], places=9)
            self.assertAlmostEqual(lhs["kappa"], -rhs["kappa"], places=12)
        self.assertAlmostEqual(state_at(left, 16.0)["yaw"], 0.8, places=6)
        self.assertAlmostEqual(state_at(right, 16.0)["yaw"], -0.8, places=6)

    def test_actor_target_uses_rigid_body_position_and_speed(self):
        row = {"x": 2.0, "y": 3.0, "yaw": 0.0, "v": 4.0, "kappa": 0.05}
        target = actor_target(row, (1.4, 0.2))
        self.assertAlmostEqual(target["x"], 3.4)
        self.assertAlmostEqual(target["y"], 3.2)
        self.assertAlmostEqual(target["speed_mps"], math.hypot(3.96, 0.28))
        with self.assertRaises(ValueError):
            actor_target(row, (1.4,))

    def test_corridor_body_and_signed_clearance_use_full_polygons(self):
        reference = generate_reference("S2")
        lane = corridor(reference)
        body = body_polygon((8.0, 0.0), 0.0, GEOMETRY)
        self.assertTrue(lane.covers(body))
        self.assertAlmostEqual(clearance(body, lane), 1.75 - GEOMETRY["width"] / 2, places=5)
        self.assertLess(clearance(body_polygon((8.0, 2.0), 0.0, GEOMETRY), lane), 0.0)

        rotated = body_polygon((0.0, 0.0), 0.0, dict(GEOMETRY, box_yaw=math.pi / 2))
        min_x, min_y, max_x, max_y = rotated.bounds
        self.assertAlmostEqual(max_x - min_x, GEOMETRY["width"], places=6)
        self.assertAlmostEqual(max_y - min_y, GEOMETRY["front"] + GEOMETRY["rear"], places=6)

    def test_frozen_corridor_densifies_the_analytic_radius_twenty_curve(self):
        reference = generate_reference("L4")
        lane = corridor(reference, "L4")
        row = state_at(reference, 13.0)  # middle of the constant kappa=0.05 section
        normal = np.array((-math.sin(row["yaw"]), math.cos(row["yaw"])))
        centerline = np.array((row["x"], row["y"]))
        circle_center = centerline + 20.0 * normal
        inner = centerline + 1.75 * normal
        outer = centerline - 1.75 * normal
        self.assertAlmostEqual(np.linalg.norm(inner - circle_center), 18.25, places=9)
        self.assertAlmostEqual(np.linalg.norm(outer - circle_center), 21.75, places=9)
        self.assertLess(lane.boundary.distance(Point(inner)), 2e-5)
        self.assertLess(lane.boundary.distance(Point(outer)), 2e-5)

    def test_validator_accepts_nominal_cases_and_rejects_tampering(self):
        for name in CASES:
            result = validate_reference(name, generate_reference(name), GEOMETRY)
            self.assertTrue(result["passed"], (name, result))
            self.assertGreaterEqual(result["metrics"]["min_body_clearance_m"], 0.30)
            self.assertLessEqual(result["metrics"]["half_step_position_max_m"], 0.0001)
            self.assertLessEqual(result["metrics"]["half_step_yaw_max_rad"], 0.00001)

        bad = copy.deepcopy(generate_reference("S2"))
        bad[20]["v"] = 9.0
        result = validate_reference("S2", bad, GEOMETRY)
        self.assertFalse(result["passed"])
        self.assertTrue(any("analytic" in error for error in result["errors"]))

        missing = generate_reference("S2")[:-1]
        self.assertFalse(validate_reference("S2", missing, GEOMETRY)["passed"])


if __name__ == "__main__":
    unittest.main()
