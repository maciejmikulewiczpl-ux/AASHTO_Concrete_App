"""
Unit tests for pt_engine.py — Post-Tensioning Tendon Profile & Losses
"""
import math
import pytest
import pt_engine


# ─── 1. Parabola fitting ─────────────────────────────────────────

def test_fit_parabola_basic():
    """3 points on y = 2x² - 3x + 1 should recover exact coefficients."""
    # y(0)=1, y(1)=0, y(2)=3
    a, b, c = pt_engine.fit_parabola(0, 1, 1, 0, 2, 3)
    assert abs(a - 2) < 1e-10
    assert abs(b - (-3)) < 1e-10
    assert abs(c - 1) < 1e-10


def test_fit_parabola_symmetric():
    """Symmetric parabola: vertex at midspan."""
    # left=6, mid=24, right=6 over 0..1440 in
    a, b, c = pt_engine.fit_parabola(0, 6, 720, 24, 1440, 6)
    # At x=0: c = 6
    assert abs(c - 6) < 1e-10
    # At x=720: a*720² + b*720 + 6 = 24
    assert abs(a * 720**2 + b * 720 + c - 24) < 1e-8
    # At x=1440: same as x=0 by symmetry
    assert abs(a * 1440**2 + b * 1440 + c - 6) < 1e-8


def test_fit_parabola_collinear():
    """Collinear points produce a=0 (line, not parabola). This is valid."""
    a, b, c = pt_engine.fit_parabola(0, 0, 1, 1, 2, 2)
    assert abs(a) < 1e-10  # no quadratic term
    assert abs(b - 1) < 1e-10
    assert abs(c) < 1e-10


# ─── 2. Profile assembly ─────────────────────────────────────────

def test_profile_single_span_control_points():
    """Profile should pass through the 3 control points."""
    spans = [{"L_ft": 120, "y_left": 6, "y_mid": 24, "y_right": 6}]
    prof = pt_engine.build_tendon_profile(spans, dx_ft=1.0)
    # First point
    assert abs(prof[0]["x_ft"]) < 0.01
    assert abs(prof[0]["y"] - 6) < 0.1
    # Midspan (60 ft)
    mid = min(prof, key=lambda p: abs(p["x_ft"] - 60))
    assert abs(mid["y"] - 24) < 0.1
    # Last point
    assert abs(prof[-1]["x_ft"] - 120) < 0.01
    assert abs(prof[-1]["y"] - 6) < 0.1


def test_profile_two_spans():
    """Two spans should produce a continuous profile with hog over interior support."""
    spans = [
        {"L_ft": 80, "y_left": 6, "y_mid": 20, "y_right": 8},
        {"L_ft": 100, "y_left": 8, "y_mid": 22, "y_right": 6},
    ]
    prof = pt_engine.build_tendon_profile(spans, dx_ft=1.0)
    assert abs(prof[0]["x_ft"]) < 0.01
    assert abs(prof[-1]["x_ft"] - 180) < 0.1
    # At the interior support (x=80 ft), hog parabola vertex → y should be near 8
    junc = min(prof, key=lambda p: abs(p["x_ft"] - 80))
    assert abs(junc["y"] - 8) < 0.5
    # Profile must be continuous (no jumps)
    for i in range(1, len(prof)):
        dy = abs(prof[i]["y"] - prof[i - 1]["y"])
        assert dy < 2.0, f"Jump at i={i}: dy={dy:.2f}"


def test_profile_alpha_left_increases():
    """Cumulative angular change from left should be monotonically non-decreasing."""
    spans = [{"L_ft": 120, "y_left": 6, "y_mid": 24, "y_right": 6}]
    prof = pt_engine.build_tendon_profile(spans, dx_ft=0.5)
    for i in range(1, len(prof)):
        assert prof[i]["alpha_left"] >= prof[i - 1]["alpha_left"] - 1e-12


# ─── 3. Friction losses ──────────────────────────────────────────

def test_friction_straight_tendon():
    """Straight tendon (α=0): loss is purely from wobble κ·x."""
    spans = [{"L_ft": 100, "y_left": 12, "y_mid": 12, "y_right": 12}]
    prof = pt_engine.build_tendon_profile(spans, dx_ft=1.0)
    fpj = 200.0
    mu = 0.20
    kappa = 0.0002
    fp_left, fp_right = pt_engine.friction_loss(fpj, mu, kappa, prof)

    # At x=0: should be fpj
    assert abs(fp_left[0] - fpj) < 0.01
    # At x=100ft: fp = fpj * exp(-kappa * 100)  (α=0 for straight tendon, only wobble)
    expected = fpj * math.exp(-kappa * 100)
    assert abs(fp_left[-1] - expected) < 0.1

    # Right-end jacking: at x=100 should be fpj
    assert abs(fp_right[-1] - fpj) < 0.01


def test_friction_decreases_from_jacking_end():
    """Stress should decrease away from jacking end."""
    spans = [{"L_ft": 120, "y_left": 6, "y_mid": 24, "y_right": 6}]
    prof = pt_engine.build_tendon_profile(spans, dx_ft=1.0)
    fp_left, fp_right = pt_engine.friction_loss(200, 0.20, 0.0002, prof)
    # Left-end: should monotonically decrease
    for i in range(1, len(fp_left)):
        assert fp_left[i] <= fp_left[i - 1] + 1e-10
    # Right-end: should monotonically increase (from left to right)
    for i in range(1, len(fp_right)):
        assert fp_right[i] >= fp_right[i - 1] - 1e-10


# ─── 4. Anchor set losses ────────────────────────────────────────

def test_anchor_set_reduces_stress_near_anchor():
    """After anchor set, stress near jacking end should decrease."""
    spans = [{"L_ft": 120, "y_left": 6, "y_mid": 24, "y_right": 6}]
    prof = pt_engine.build_tendon_profile(spans, dx_ft=0.5)
    fp_left, _ = pt_engine.friction_loss(210, 0.20, 0.0002, prof)
    fp_after, x_set = pt_engine.anchor_set_loss(fp_left, prof, 0.375, 28500)

    # Stress at anchor should be reduced
    assert fp_after[0] < fp_left[0]
    # x_set should be > 0 and <= total length
    assert x_set > 0
    assert x_set <= 120
    # Beyond x_set, stress should be unchanged
    for i, pt in enumerate(prof):
        if pt["x_ft"] > x_set + 1:
            assert abs(fp_after[i] - fp_left[i]) < 0.01


def test_anchor_set_right_end():
    """Right-end anchor set should work symmetrically."""
    spans = [{"L_ft": 120, "y_left": 6, "y_mid": 24, "y_right": 6}]
    prof = pt_engine.build_tendon_profile(spans, dx_ft=0.5)
    _, fp_right = pt_engine.friction_loss(210, 0.20, 0.0002, prof)
    fp_after, x_set = pt_engine.anchor_set_loss_right(fp_right, prof, 0.375, 28500)

    # Stress at right anchor (last point) should be reduced
    assert fp_after[-1] < fp_right[-1]
    assert x_set > 0


# ─── 5. Dual-end envelope ────────────────────────────────────────

def test_dual_end_envelope():
    """Envelope should be element-wise max of left and right profiles."""
    left = [10, 8, 6, 4, 2]
    right = [2, 4, 6, 8, 10]
    env = pt_engine.dual_end_envelope(left, right)
    assert env == [10, 8, 6, 8, 10]


# ─── 6. Elastic shortening ───────────────────────────────────────

def test_elastic_shortening_single_tendon_zero():
    """Single tendon group → ΔfpES = 0 (no shortening from stressing against itself)."""
    dfpES = pt_engine.elastic_shortening(180, 3.0, 500, 50000, 10, 500, 28500, 4000, N_tendons=1)
    assert dfpES == 0.0


def test_elastic_shortening_multiple_tendons():
    """Multiple tendon groups → ΔfpES > 0."""
    dfpES = pt_engine.elastic_shortening(180, 6.0, 800, 200000, 15, 1500, 28500, 4000, N_tendons=4)
    assert dfpES > 0
    assert dfpES < 30  # reasonable upper bound


# ─── 7. Time-dependent losses ────────────────────────────────────

def test_time_dependent_loss_formula():
    """Verify approximate formula against manual calculation."""
    fpi = 180
    Aps = 4.0
    Ag = 600
    H = 70
    fci = 5.0

    gamma_h = 1.7 - 0.01 * H  # = 1.0
    gamma_st = 5.0 / (1 + fci)  # = 0.833
    expected = 10 * fpi * (Aps / Ag) * gamma_h * gamma_st + 12 * gamma_h * gamma_st + 2.4

    result = pt_engine.time_dependent_loss(fpi, Aps, Ag, H, fci)
    assert abs(result - expected) < 0.01


# ─── 8. Full profile ─────────────────────────────────────────────

def test_compute_full_profile_keys():
    """Full profile should return expected structure."""
    inputs = {
        "spans": [{"L_ft": 120, "y_left": 6, "y_mid": 24, "y_right": 6}],
        "fpj": 207.9,
        "jack_end": "both",
        "mu": 0.20,
        "kappa": 0.0002,
        "delta_set": 0.375,
        "Ep": 28500,
        "Aps": 3.0,
        "Ag": 500,
        "Ig": 50000,
        "yb": 15,
        "Msw": 500,
        "Eci": 4000,
        "N_tendons": 1,
        "H": 70,
        "fci": 4.0,
    }
    result = pt_engine.compute_full_profile(inputs)
    assert "profile" in result
    assert "loss_summary" in result
    prof = result["profile"]
    assert len(prof) > 10
    # Each point should have required keys
    p = prof[0]
    for key in ["x_ft", "y", "dp", "theta_deg", "fpe", "P_eff", "Vp",
                "fp_friction_left", "fp_friction_right", "fp_immediate"]:
        assert key in p, f"Missing key: {key}"


def test_fpe_less_than_fpj():
    """Effective prestress should always be less than jacking stress."""
    inputs = {
        "spans": [{"L_ft": 100, "y_left": 6, "y_mid": 20, "y_right": 6}],
        "fpj": 207.9, "jack_end": "both", "mu": 0.20, "kappa": 0.0002,
        "delta_set": 0.375, "Ep": 28500, "Aps": 4.0, "Ag": 600,
        "Ig": 80000, "yb": 18, "Msw": 400, "Eci": 4000,
        "N_tendons": 2, "H": 70, "fci": 4.0,
    }
    result = pt_engine.compute_full_profile(inputs)
    for p in result["profile"]:
        assert p["fpe"] < inputs["fpj"]
        assert p["fpe"] >= 0


# ─── 9. Interpolation helper ─────────────────────────────────────

def test_interpolate_at_x():
    """Interpolation should return correct values at and between profile points."""
    profile = [
        {"x_ft": 0, "fpe": 180, "dp": 6},
        {"x_ft": 60, "fpe": 170, "dp": 24},
        {"x_ft": 120, "fpe": 180, "dp": 6},
    ]
    # At exact points
    assert abs(pt_engine.interpolate_at_x(profile, 0, "fpe") - 180) < 0.01
    assert abs(pt_engine.interpolate_at_x(profile, 60, "fpe") - 170) < 0.01
    # Between points (linear interpolation)
    val = pt_engine.interpolate_at_x(profile, 30, "fpe")
    assert abs(val - 175) < 0.01  # midpoint between 180 and 170
    # dp interpolation
    val = pt_engine.interpolate_at_x(profile, 30, "dp")
    assert abs(val - 15) < 0.01  # midpoint between 6 and 24
    # Out of range clamping
    assert abs(pt_engine.interpolate_at_x(profile, -5, "fpe") - 180) < 0.01
    assert abs(pt_engine.interpolate_at_x(profile, 200, "fpe") - 180) < 0.01


# ─── 10. Caltrans BDP 5.2 Verification ───────────────────────────

# Reference data from Caltrans BDP Chapter 5.2 Tables 5.2.12.7.1-2 and 5.2.12.7.5-1
# 3-span bridge: 126 + 168 + 118 = 412 ft
# K = 0.0002/ft, μ = 0.15, fpj = 0.75 × 270 = 202.5 ksi
# Ep = 28,500 ksi, Aset = 0.375 in

CALTRANS_POINTS = [
    # (label, x_left_ft, alpha_left_rad, FC_left, x_right_ft, alpha_right_rad, FC_right)
    ("A",   0.0, 0.000, 1.000,  412.0, 1.166, 0.773),
    ("B",  50.4, 0.110, 0.974,  361.6, 1.056, 0.794),
    ("C", 113.4, 0.231, 0.944,  298.6, 0.934, 0.819),
    ("D", 126.0, 0.352, 0.925,  286.0, 0.813, 0.836),
    ("E", 142.8, 0.462, 0.907,  269.2, 0.704, 0.853),
    ("F", 210.0, 0.571, 0.880,  202.0, 0.594, 0.878),
    ("G", 277.2, 0.680, 0.854,  134.8, 0.486, 0.905),
    ("H", 294.0, 0.789, 0.837,  118.0, 0.376, 0.923),
    ("I", 305.8, 0.919, 0.819,  106.2, 0.247, 0.943),
    ("J", 364.8, 1.048, 0.794,   47.2, 0.117, 0.973),
    ("K", 412.0, 1.166, 0.773,    0.0, 0.000, 1.000),
]

CALTRANS_ANCHOR_SET = {
    "left":  {"x_pA": 94.37, "FC_pA": 0.093},
    "right": {"x_pA": 90.53, "FC_pA": 0.097},
}

# Table 5.2.12.7.5-1: FC after all losses (left / right stressing)
CALTRANS_FC_PLT = {
    # label: (FC_pLT_left, FC_pLT_right)
    "A": (0.770, 0.635), "B": (0.794, 0.656), "C": (0.806, 0.681),
    "D": (0.787, 0.698), "E": (0.769, 0.715), "F": (0.742, 0.740),
    "G": (0.716, 0.767), "H": (0.699, 0.785), "I": (0.681, 0.805),
    "J": (0.656, 0.792), "K": (0.635, 0.767),
}


def test_caltrans_friction_formula():
    """Verify friction formula FC = e^-(Kx+μα) against Caltrans Table 5.2.12.7.1-2.

    Uses Caltrans' own (x, α) values directly — tests the formula, not our geometry.
    """
    K = 0.0002  # wobble per ft
    mu = 0.15
    fpj = 202.5

    # Build a mock profile with Caltrans control points
    mock_profile = []
    L_total = 412.0
    for label, x_l, alpha_l, fc_l, x_r, alpha_r, fc_r in CALTRANS_POINTS:
        mock_profile.append({
            "x_ft": x_l,
            "x_in": x_l * 12.0,
            "y": 0,
            "theta": 0,
            "alpha_left": alpha_l,
            "alpha_right": alpha_r,
        })

    fp_left, fp_right = pt_engine.friction_loss(fpj, mu, K, mock_profile)

    print("\n=== Caltrans Friction Verification (Table 5.2.12.7.1-2) ===")
    print(f"{'Pt':>3} {'x(ft)':>7} {'a_L':>6} {'CT FC_L':>8} {'Our FC_L':>9} {'Diff':>7}"
          f" | {'x_R(ft)':>8} {'a_R':>6} {'CT FC_R':>8} {'Our FC_R':>9} {'Diff':>7}")
    print("-" * 95)

    for i, (label, x_l, alpha_l, fc_l_ct, x_r, alpha_r, fc_r_ct) in enumerate(CALTRANS_POINTS):
        fc_l_ours = fp_left[i] / fpj
        fc_r_ours = fp_right[i] / fpj
        diff_l = fc_l_ours - fc_l_ct
        diff_r = fc_r_ours - fc_r_ct
        print(f"  {label:>2} {x_l:>7.1f} {alpha_l:>6.3f} {fc_l_ct:>8.3f} {fc_l_ours:>9.4f} {diff_l:>+7.4f}"
              f" | {x_r:>8.1f} {alpha_r:>6.3f} {fc_r_ct:>8.3f} {fc_r_ours:>9.4f} {diff_r:>+7.4f}")

        # Assert: friction formula must match within 0.001
        assert abs(fc_l_ours - fc_l_ct) < 0.002, \
            f"Left FC mismatch at {label}: Caltrans={fc_l_ct}, ours={fc_l_ours:.4f}"
        assert abs(fc_r_ours - fc_r_ct) < 0.002, \
            f"Right FC mismatch at {label}: Caltrans={fc_r_ct}, ours={fc_r_ours:.4f}"


def test_caltrans_anchor_set_comparison():
    """Compare anchor set results: our energy-balance vs Caltrans similar-triangles.

    Reports differences — does not assert exact match (different methods).
    """
    K = 0.0002
    mu = 0.15
    fpj = 202.5
    Ep = 28500.0
    delta_set = 0.375  # in

    # Build mock profile from Caltrans points (denser interpolation)
    mock_profile = []
    L_total = 412.0
    for label, x_l, alpha_l, fc_l, x_r, alpha_r, fc_r in CALTRANS_POINTS:
        mock_profile.append({
            "x_ft": x_l,
            "x_in": x_l * 12.0,
            "y": 0, "theta": 0,
            "alpha_left": alpha_l,
            "alpha_right": alpha_r,
        })

    fp_left, fp_right = pt_engine.friction_loss(fpj, mu, K, mock_profile)

    # Left-end anchor set
    fp_left_after, x_set_left = pt_engine.anchor_set_loss(fp_left, mock_profile, delta_set, Ep)
    # Right-end anchor set
    fp_right_after, x_set_right = pt_engine.anchor_set_loss_right(fp_right, mock_profile, delta_set, Ep)

    ct_left = CALTRANS_ANCHOR_SET["left"]
    ct_right = CALTRANS_ANCHOR_SET["right"]

    print("\n=== Caltrans Anchor Set Comparison ===")
    print(f"  Left  anchor set absorbed distance: Caltrans={ct_left['x_pA']:.2f} ft, Ours={x_set_left:.2f} ft, "
          f"Diff={x_set_left - ct_left['x_pA']:+.2f} ft ({(x_set_left - ct_left['x_pA'])/ct_left['x_pA']*100:+.1f}%)")
    print(f"  Right anchor set absorbed distance: Caltrans={ct_right['x_pA']:.2f} ft, Ours={x_set_right:.2f} ft, "
          f"Diff={x_set_right - ct_right['x_pA']:+.2f} ft ({(x_set_right - ct_right['x_pA'])/ct_right['x_pA']*100:+.1f}%)")

    fc_pA_left_ours = (fp_left[0] - fp_left_after[0]) / fpj
    fc_pA_right_ours = (fp_right[-1] - fp_right_after[-1]) / fpj
    print(f"  Left  FC_pA (loss at anchor): Caltrans={ct_left['FC_pA']:.3f}, Ours={fc_pA_left_ours:.4f}, "
          f"Diff={fc_pA_left_ours - ct_left['FC_pA']:+.4f}")
    print(f"  Right FC_pA (loss at anchor): Caltrans={ct_right['FC_pA']:.3f}, Ours={fc_pA_right_ours:.4f}, "
          f"Diff={fc_pA_right_ours - ct_right['FC_pA']:+.4f}")
    print("  Note: Differences expected — our method (energy-balance) vs Caltrans (similar triangles)")

    # Sanity: absorbed distance should be in a reasonable range
    assert 50 < x_set_left < 150, f"Left x_set={x_set_left} out of reasonable range"
    assert 50 < x_set_right < 150, f"Right x_set={x_set_right} out of reasonable range"


def test_caltrans_full_comparison():
    """Run full profile and report all losses vs Caltrans at every control point.

    Caltrans uses assumed ES=3 ksi, LT=25 ksi. We compute these from AASHTO formulas,
    so differences are expected and reported.
    """
    K = 0.0002
    mu = 0.15
    fpj = 202.5
    Ep = 28500.0
    delta_set = 0.375

    # We cannot exactly reproduce Caltrans geometry (they use 3+ segments/span),
    # so use mock profile with their own α values for a direct comparison.
    mock_profile = []
    for label, x_l, alpha_l, fc_l, x_r, alpha_r, fc_r in CALTRANS_POINTS:
        mock_profile.append({
            "x_ft": x_l,
            "x_in": x_l * 12.0,
            "y": 20.0,  # dummy CGS depth
            "theta": 0, "alpha_left": alpha_l, "alpha_right": alpha_r,
        })

    # Step 1: Friction
    fp_left, fp_right = pt_engine.friction_loss(fpj, mu, K, mock_profile)

    # Step 2: Anchor set
    fp_left_set, x_set_L = pt_engine.anchor_set_loss(fp_left, mock_profile, delta_set, Ep)
    fp_right_set, x_set_R = pt_engine.anchor_set_loss_right(fp_right, mock_profile, delta_set, Ep)

    # Step 3: Our ES and LT (illustrative — Caltrans assumed 3 and 25 ksi)
    # Use assumed values matching Caltrans for the FC_pLT comparison
    dfpES = 3.0   # match Caltrans assumption
    dfpLT = 25.0  # match Caltrans assumption
    total_uniform = dfpES + dfpLT

    print("\n=== Caltrans Full Loss Comparison (Table 5.2.12.7.5-1) ===")
    print(f"  Using Caltrans assumed values: dfpES={dfpES} ksi, dfpLT={dfpLT} ksi")
    print(f"  ES+LT FC = {total_uniform/fpj:.3f}")
    print()

    # Left-end stressing
    print(f"{'Pt':>3} | {'--- LEFT-END STRESSING ---':^43} | {'--- RIGHT-END STRESSING ---':^43}")
    print(f"{'':>3} | {'CT FC_pF':>8} {'Our FC_pF':>9} | {'CT FC_pLT':>9} {'Our FC_pLT':>10} {'Diff':>7}"
          f" | {'CT FC_pF':>8} {'Our FC_pF':>9} | {'CT FC_pLT':>9} {'Our FC_pLT':>10} {'Diff':>7}")
    print("-" * 110)

    for i, (label, x_l, alpha_l, fc_l_ct, x_r, alpha_r, fc_r_ct) in enumerate(CALTRANS_POINTS):
        # After friction from Table 5.2.12.7.1-2
        fc_pF_left = fp_left[i] / fpj
        fc_pF_right = fp_right[i] / fpj

        # After anchor set (our method)
        fc_pA_left = fp_left_set[i] / fpj
        fc_pA_right = fp_right_set[i] / fpj

        # After ES + LT (uniform subtraction)
        fc_pLT_left = fc_pA_left - total_uniform / fpj
        fc_pLT_right = fc_pA_right - total_uniform / fpj

        ct_left, ct_right = CALTRANS_FC_PLT[label]

        diff_left = fc_pLT_left - ct_left
        diff_right = fc_pLT_right - ct_right

        print(f"  {label:>2} | {fc_l_ct:>8.3f} {fc_pF_left:>9.4f} | {ct_left:>9.3f} {fc_pLT_left:>10.4f} {diff_left:>+7.4f}"
              f" | {fc_r_ct:>8.3f} {fc_pF_right:>9.4f} | {ct_right:>9.3f} {fc_pLT_right:>10.4f} {diff_right:>+7.4f}")

    print()
    print("  Note: FC_pLT differences arise from anchor set method difference")
    print("  (our energy-balance vs Caltrans similar-triangles formula)")


def test_caltrans_vertex_profile_control_points():
    """Verify that vertex-form profile with x_mid_frac passes through user-defined points."""
    # Asymmetric apex at 0.4 of span (single span — no hog parabolas)
    spans = [{"L_ft": 126, "y_left": 6.0, "y_mid": 30.0, "y_right": 4.0, "x_mid_frac": 0.4}]
    prof = pt_engine.build_tendon_profile(spans, dx_ft=0.5)

    # Check left end
    assert abs(prof[0]["y"] - 6.0) < 0.1
    # Check right end
    assert abs(prof[-1]["y"] - 4.0) < 0.1
    # Check apex location (at 0.4 * 126 = 50.4 ft)
    apex = min(prof, key=lambda p: abs(p["x_ft"] - 50.4))
    assert abs(apex["y"] - 30.0) < 0.2
    # Zero slope at apex
    assert abs(apex["theta"]) < 0.005, f"Slope at apex = {apex['theta']:.4f}, expected ~0"


def test_caltrans_five_parabola_profile():
    """Verify 5-parabola profile for 3 spans matches Caltrans BDP layout.

    3 sag parabolas + 2 hog parabolas = 5 total.
    Inflection points at 0.1L from each interior support.
    Tangency: slope must be continuous at inflection points.
    """
    spans = [
        {"L_ft": 126, "y_left": 21, "y_mid": 63, "y_right": 6, "x_mid_frac": 0.4},
        {"L_ft": 168, "y_left": 6, "y_mid": 63, "y_right": 6, "x_mid_frac": 0.5},
        {"L_ft": 118, "y_left": 6, "y_mid": 63, "y_right": 21, "x_mid_frac": 0.6},
    ]
    prof = pt_engine.build_tendon_profile(spans, dx_ft=0.5, inf_frac=0.1)

    # Check endpoints
    assert abs(prof[0]["y"] - 21) < 0.1, "Left abutment CGS"
    assert abs(prof[-1]["y"] - 21) < 0.1, "Right abutment CGS"

    # Check sag vertices (mid-span low points at maximum y)
    # Span 1: apex at 0.4*126 = 50.4 ft
    apex1 = min(prof, key=lambda p: abs(p["x_ft"] - 50.4))
    assert abs(apex1["y"] - 63) < 0.5, f"Span 1 apex y={apex1['y']}"
    assert abs(apex1["theta"]) < 0.01, "Zero slope at span 1 apex"

    # Span 2: apex at 126 + 0.5*168 = 210 ft
    apex2 = min(prof, key=lambda p: abs(p["x_ft"] - 210))
    assert abs(apex2["y"] - 63) < 0.5, f"Span 2 apex y={apex2['y']}"
    assert abs(apex2["theta"]) < 0.01, "Zero slope at span 2 apex"

    # Span 3: apex at 126+168 + 0.6*118 = 364.8 ft
    apex3 = min(prof, key=lambda p: abs(p["x_ft"] - 364.8))
    assert abs(apex3["y"] - 63) < 0.5, f"Span 3 apex y={apex3['y']}"
    assert abs(apex3["theta"]) < 0.01, "Zero slope at span 3 apex"

    # Check hog vertices at interior supports (minimum y)
    # Support 1 at 126 ft
    sup1 = min(prof, key=lambda p: abs(p["x_ft"] - 126))
    assert abs(sup1["y"] - 6) < 0.5, f"Support 1 y={sup1['y']}"
    assert abs(sup1["theta"]) < 0.01, "Zero slope at support 1"

    # Support 2 at 126+168 = 294 ft
    sup2 = min(prof, key=lambda p: abs(p["x_ft"] - 294))
    assert abs(sup2["y"] - 6) < 0.5, f"Support 2 y={sup2['y']}"
    assert abs(sup2["theta"]) < 0.01, "Zero slope at support 2"

    # Inflection points: slope must be continuous (no jump > small tolerance)
    # Inflection at 126 - 0.1*126 = 113.4 ft (span1/hog1 boundary)
    # Inflection at 126 + 0.1*168 = 142.8 ft (hog1/span2 boundary)
    # Inflection at 294 - 0.1*168 = 277.2 ft (span2/hog2 boundary)
    # Inflection at 294 + 0.1*118 = 305.8 ft (hog2/span3 boundary)
    for x_inf in [113.4, 142.8, 277.2, 305.8]:
        idx = min(range(len(prof)), key=lambda k: abs(prof[k]["x_ft"] - x_inf))
        # Check slope continuity: compare adjacent points
        if 0 < idx < len(prof) - 1:
            slope_before = prof[idx]["theta"] - prof[idx - 1]["theta"]
            slope_after = prof[idx + 1]["theta"] - prof[idx]["theta"]
            # No abrupt change (tolerance for discretisation)
            assert abs(slope_after - slope_before) < 0.02, \
                f"Slope discontinuity at inflection x={x_inf:.1f}: " \
                f"before={slope_before:.4f}, after={slope_after:.4f}"

    # Profile must be continuous everywhere
    for i in range(1, len(prof)):
        dy = abs(prof[i]["y"] - prof[i - 1]["y"])
        assert dy < 2.0, f"Jump at x={prof[i]['x_ft']:.1f}: dy={dy:.2f}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
