"""
Post-Tensioning Tendon Profile & Losses Engine
================================================
Computes:
  - Multi-span parabolic tendon geometry
  - Friction losses           (AASHTO 5.9.3.2.2b)
  - Anchor set losses         (AASHTO 5.9.3.2.1)
  - Elastic shortening        (AASHTO 5.9.3.2.3a)
  - Time-dependent losses     (AASHTO 5.9.3.3 Approximate)
  - Effective prestress profile, Vp, dp at any section x

Units: kip, in, ksi throughout (spans entered in ft, converted internally)
"""

import math

# ---------------------------------------------------------------------------
# 1. Parabola fitting
# ---------------------------------------------------------------------------

def fit_parabola(x1, y1, x2, y2, x3, y3):
    """Fit y = a*x^2 + b*x + c through three points.
    Returns (a, b, c)."""
    # Solve 3x3 system via direct elimination
    # [x1^2  x1  1] [a]   [y1]
    # [x2^2  x2  1] [b] = [y2]
    # [x3^2  x3  1] [c]   [y3]
    d = (x1 - x2) * (x1 - x3) * (x2 - x3)
    if abs(d) < 1e-15:
        raise ValueError("Three points are collinear or coincident — cannot fit parabola")
    a = (x3 * (y2 - y1) + x2 * (y1 - y3) + x1 * (y3 - y2)) / d
    b = (x3 * x3 * (y1 - y2) + x2 * x2 * (y3 - y1) + x1 * x1 * (y2 - y3)) / d
    c = (x2 * x3 * (x2 - x3) * y1 + x3 * x1 * (x3 - x1) * y2 + x1 * x2 * (x1 - x2) * y3) / d
    return (a, b, c)


# ---------------------------------------------------------------------------
# 2. Multi-parabola tendon profile assembly
# ---------------------------------------------------------------------------

def build_tendon_profile(parabolas, dx_ft=0.5, **_ignored):
    """Build discretised tendon profile from an explicit list of parabolas.

    Each parabola is defined by three control points: left (x_L, y_L),
    vertex/mid (x_M, y_M), and right (x_R, y_R).  The vertex has zero
    slope.  Left and right sides use independent *a* coefficients so
    the parabola passes exactly through all three points:

        y = a_left  * (x - x_M)^2 + y_M   for x <= x_M
        y = a_right * (x - x_M)^2 + y_M   for x >  x_M

    Adjacent parabolas must share an endpoint (the right point of
    parabola *i* equals the left point of parabola *i + 1*).  Tangency
    at these junctions is automatic because both neighbouring vertices
    have zero slope and the shared point lies on both curves.

    Parameters
    ----------
    parabolas : list of dict
        Each dict has keys:
            x_left, y_left   – left endpoint (ft / in)
            x_mid, y_mid     – vertex / apex (ft / in)
            x_right, y_right – right endpoint (ft / in)
    dx_ft : float
        Discretisation step in feet (default 0.5 ft).

    Returns
    -------
    profile : list of dict
        Each entry: {x_ft, x_in, y, theta, alpha_left, alpha_right}

    Legacy compatibility
    --------------------
    If the first element of *parabolas* contains the key ``L_ft``
    (old span-based format) the function delegates to a legacy
    converter so existing tests / callers keep working.
    """
    # --- Legacy format detection ---
    if parabolas and "L_ft" in parabolas[0]:
        parabolas = _legacy_spans_to_parabolas(parabolas, _ignored.get("inf_frac", 0.1))

    dx_in = dx_ft * 12.0
    profile = []

    for pi, par in enumerate(parabolas):
        xL = par["x_left"] * 12.0    # convert ft → in
        xM = par["x_mid"] * 12.0
        xR = par["x_right"] * 12.0
        yM = par["y_mid"]
        yL = par["y_left"]
        yR = par["y_right"]

        dxL = xL - xM
        dxR = xR - xM
        aL = (yL - yM) / (dxL ** 2) if abs(dxL) > 1e-6 else 0.0
        aR = (yR - yM) / (dxR ** 2) if abs(dxR) > 1e-6 else 0.0

        seg_len = xR - xL
        n_pts = max(int(round(seg_len / dx_in)), 1) + 1
        for j in range(n_pts):
            x = xL + j * seg_len / (n_pts - 1)
            if pi > 0 and j == 0:
                continue  # shared point with previous parabola
            if x <= xM:
                y = aL * (x - xM) ** 2 + yM
                dydx = 2.0 * aL * (x - xM)
            else:
                y = aR * (x - xM) ** 2 + yM
                dydx = 2.0 * aR * (x - xM)
            theta = math.atan(dydx)
            profile.append({
                "x_ft": x / 12.0,
                "x_in": x,
                "y": y,
                "theta": theta,
                "alpha_left": 0.0,
                "alpha_right": 0.0,
            })

    # ---- Cumulative angular change from left ----
    for i in range(1, len(profile)):
        dtheta = abs(profile[i]["theta"] - profile[i - 1]["theta"])
        profile[i]["alpha_left"] = profile[i - 1]["alpha_left"] + dtheta

    # ---- Cumulative angular change from right ----
    n = len(profile)
    for i in range(n - 2, -1, -1):
        dtheta = abs(profile[i]["theta"] - profile[i + 1]["theta"])
        profile[i]["alpha_right"] = profile[i + 1]["alpha_right"] + dtheta

    return profile


def _legacy_spans_to_parabolas(spans, inf_frac=0.1):
    """Convert old span-based input to explicit parabola list.

    Used for backward compatibility with tests that pass
    [{L_ft, y_left, y_mid, y_right, x_mid_frac, ...}, ...].
    """
    N = len(spans)
    parabolas = []
    x_off = 0.0  # cumulative x in ft

    for i, sp in enumerate(spans):
        L = sp["L_ft"]
        xmf = sp.get("x_mid_frac", 0.5)
        x_v = x_off + xmf * L
        y_v = sp["y_mid"]
        y_L = sp["y_left"]
        y_R = sp["y_right"]
        inf_L = sp.get("inf_left", inf_frac) if i > 0 else 0.0
        inf_R = sp.get("inf_right", inf_frac) if i < N - 1 else 0.0

        # Sag parabola
        if i == 0:
            x_sag_L = x_off
            y_sag_L = y_L
        else:
            x_inf = x_off + inf_L * L
            t = (x_inf - x_off) / (x_v - x_off) if abs(x_v - x_off) > 1e-6 else 0.0
            x_sag_L = x_inf
            y_sag_L = y_L + t * (y_v - y_L)

        if i == N - 1:
            x_sag_R = x_off + L
            y_sag_R = y_R
        else:
            x_sup_R = x_off + L
            x_inf_R = x_sup_R - inf_R * L
            t = (x_inf_R - x_v) / (x_sup_R - x_v) if abs(x_sup_R - x_v) > 1e-6 else 0.0
            x_sag_R = x_inf_R
            y_sag_R = y_v + t * (y_R - y_v)

        parabolas.append({
            "x_left": x_sag_L, "y_left": y_sag_L,
            "x_mid": x_v, "y_mid": y_v,
            "x_right": x_sag_R, "y_right": y_sag_R,
        })

        # Hog parabola over right interior support
        if i < N - 1:
            x_sup = x_off + L
            y_sup = y_R
            x_hog_L = x_sag_R
            y_hog_L = y_sag_R

            nsp = spans[i + 1]
            nL = nsp["L_ft"]
            nxmf = nsp.get("x_mid_frac", 0.5)
            nx_v = x_sup + nxmf * nL
            ny_v = nsp["y_mid"]
            n_inf_L = nsp.get("inf_left", inf_frac)
            x_inf_next = x_sup + n_inf_L * nL
            t = (x_inf_next - x_sup) / (nx_v - x_sup) if abs(nx_v - x_sup) > 1e-6 else 0.0
            x_hog_R = x_inf_next
            y_hog_R = y_sup + t * (ny_v - y_sup)

            parabolas.append({
                "x_left": x_hog_L, "y_left": y_hog_L,
                "x_mid": x_sup, "y_mid": y_sup,
                "x_right": x_hog_R, "y_right": y_hog_R,
            })

        x_off += L

    return parabolas

    return profile


# ---------------------------------------------------------------------------
# 3. Friction losses  (AASHTO 5.9.3.2.2b)
# ---------------------------------------------------------------------------

def friction_loss(fpj, mu, kappa_per_ft, profile):
    """Compute friction stress from both jacking ends.

    Parameters
    ----------
    fpj : float       – jacking stress (ksi)
    mu  : float       – friction coefficient
    kappa_per_ft : float – wobble coefficient (per ft)
    profile : list    – from build_tendon_profile

    Returns
    -------
    fp_left  : list of float – stress at each point, jacked from left
    fp_right : list of float – stress at each point, jacked from right

    Formula per AASHTO 5.9.3.2.2b-1:
        fp(x) = fpj * e^-(K*x + μ*α)
    where K = wobble coefficient (kappa_per_ft), μ = friction coefficient (mu),
    x = distance from jacking end, α = cumulative angular change.
    """
    kappa = kappa_per_ft  # already per ft
    fp_left = []
    fp_right = []
    for pt in profile:
        # From left end
        alpha_l = pt["alpha_left"]
        x_ft = pt["x_ft"]
        fp_left.append(fpj * math.exp(-(mu * alpha_l + kappa * x_ft)))
        # From right end
        alpha_r = pt["alpha_right"]
        L_total_ft = profile[-1]["x_ft"]
        dist_from_right = L_total_ft - x_ft
        fp_right.append(fpj * math.exp(-(mu * alpha_r + kappa * dist_from_right)))
    return fp_left, fp_right


# ---------------------------------------------------------------------------
# 4. Anchor set losses  (AASHTO 5.9.3.2.1)
# ---------------------------------------------------------------------------

def anchor_set_loss(stress_array, profile, delta_set_in, Ep):
    """Apply anchor-set loss to a friction stress profile.

    Uses the "mirror / reflected line" method:
      – The reflected stress at x (from the anchor end) is
        fp_reflected(x) = 2·fp(x_set) − fp(x)
      – x_set is found so that the area between the original and reflected
        curves equals Δ_set × Ep  (strain energy balance).

    Parameters
    ----------
    stress_array : list of float – friction stress at each profile point (from this end)
    profile      : list of dict  – tendon profile (with x_in)
    delta_set_in : float         – anchor set (inches)
    Ep           : float         – tendon modulus (ksi)

    Returns
    -------
    stress_after : list of float – stress after anchor set at each point
    x_set_ft     : float         – distance from anchor where set is fully absorbed (ft)
    """
    n = len(stress_array)
    if n < 2 or delta_set_in <= 0:
        return list(stress_array), 0.0

    # Target area = delta_set * Ep (ksi·in → consistent with stress in ksi, dx in in)
    target_area = delta_set_in * Ep

    # Integrate from anchor end (index 0) inward, accumulating area
    # area(j) = Σ (fp[0..j] reflected area) = Σ 2·(fp[j]-fp[i])·dx
    # Actually: area = integral of [fp_before - fp_after] dx
    # fp_before(i) = stress_array[i]
    # fp_after(i)  = 2·stress_array[j] - stress_array[i]   for i <= j
    # diff(i) = fp_before(i) - fp_after(i) = 2·(stress_array[i] - stress_array[j])
    # Wait — stress decreases away from anchor, so stress_array[0] > stress_array[j].
    # diff(i) = stress_array[i] - (2·stress_array[j] - stress_array[i]) = 2·(stress_array[i] - stress_array[j])
    # area(j) = Σ_{i=0}^{j-1} 2·(stress_array[i] - stress_array[j]) · Δx_i
    # We seek j where area(j) = target_area.

    # Precompute cumulative stress-area from anchor end
    cum_stress_x = [0.0]  # integral of stress · dx from anchor
    cum_x = [0.0]         # integral of dx from anchor
    for i in range(1, n):
        dx = profile[i]["x_in"] - profile[i - 1]["x_in"]
        avg_stress = 0.5 * (stress_array[i - 1] + stress_array[i])
        cum_stress_x.append(cum_stress_x[-1] + avg_stress * dx)
        cum_x.append(cum_x[-1] + dx)

    # For candidate set point at index j:
    # area(j) = 2 * [stress_array[j] * cum_x[j] - cum_stress_x[j]]
    # Wait, let me re-derive:
    # area(j) = integral_0^x_j  2*(stress(x) - stress(x_j)) dx
    #         = 2 * [integral_0^x_j stress(x) dx  - stress(x_j) * x_j ]
    #         = 2 * [cum_stress_x[j] - stress_array[j] * cum_x[j]]
    # But stress(x) > stress(x_j) for x < x_j (friction decay from anchor)
    # so area > 0.  Actually stress_array[0] = fpj (max at anchor), and decreases.
    # So stress(x) >= stress(x_j) for x <= x_j.  Correct.

    x_set_idx = n - 1  # fallback: entire length
    x_set_ft = profile[-1]["x_ft"]
    found = False

    for j in range(1, n):
        area_j = 2.0 * (cum_stress_x[j] - stress_array[j] * cum_x[j])
        if area_j >= target_area:
            # Linearly interpolate between j-1 and j
            area_prev = 2.0 * (cum_stress_x[j - 1] - stress_array[j - 1] * cum_x[j - 1])
            if area_j - area_prev > 1e-12:
                frac = (target_area - area_prev) / (area_j - area_prev)
            else:
                frac = 0.0
            x_set_idx = j
            x_set_ft = profile[j - 1]["x_ft"] + frac * (profile[j]["x_ft"] - profile[j - 1]["x_ft"])
            found = True
            break

    # Build after-set stress array
    stress_after = list(stress_array)
    if found:
        # Interpolate stress at x_set
        frac_for_stress = frac  # same fraction as above
        fp_at_set = stress_array[x_set_idx - 1] + frac_for_stress * (stress_array[x_set_idx] - stress_array[x_set_idx - 1])
        for i in range(x_set_idx):
            # Reflect: fp_after(i) = 2·fp(x_set) - fp(i)
            reflected = 2.0 * fp_at_set - stress_array[i]
            # Cannot exceed original (sanity)
            stress_after[i] = min(reflected, stress_array[i])
    else:
        # Anchor set extends entire length — unlikely but handle gracefully
        # Reduce uniformly so total area = target_area
        total_area = 2.0 * (cum_stress_x[-1] - stress_array[-1] * cum_x[-1])
        if total_area > 1e-12:
            ratio = target_area / total_area
        else:
            ratio = 0.0
        for i in range(n):
            loss = (stress_array[i] - stress_array[-1]) * ratio
            stress_after[i] = stress_array[i] - 2.0 * loss

    return stress_after, x_set_ft


def anchor_set_loss_right(stress_array, profile, delta_set_in, Ep):
    """Apply anchor-set loss for right-end jacking.

    Same algorithm as anchor_set_loss but working from the right end inward.
    We reverse the arrays, apply the standard method, then reverse back.
    """
    rev_stress = list(reversed(stress_array))
    # Build a reversed profile with x_in measured from right end
    n = len(profile)
    L_total_in = profile[-1]["x_in"]
    rev_profile = []
    for i in range(n - 1, -1, -1):
        rev_profile.append({
            "x_ft": (L_total_in - profile[i]["x_in"]) / 12.0,
            "x_in": L_total_in - profile[i]["x_in"],
        })

    rev_after, x_set_ft = anchor_set_loss(rev_stress, rev_profile, delta_set_in, Ep)
    stress_after = list(reversed(rev_after))
    return stress_after, x_set_ft


# ---------------------------------------------------------------------------
# 5. Dual-end jacking envelope
# ---------------------------------------------------------------------------

def dual_end_envelope(fp_left_set, fp_right_set):
    """Return element-wise max of two stress arrays (dual-end jacking envelope)."""
    return [max(l, r) for l, r in zip(fp_left_set, fp_right_set)]


# ---------------------------------------------------------------------------
# 6. Elastic shortening  (AASHTO 5.9.3.2.3a)
# ---------------------------------------------------------------------------

def elastic_shortening(fp_avg, Aps, Ag, Ig, e_cgs, Msw_kft, Ep, Eci, N_tendons=1):
    """Compute elastic shortening loss ΔfpES.

    Parameters
    ----------
    fp_avg     : float – average stress after friction + anchor set (ksi)
    Aps        : float – total strand area (in²)
    Ag         : float – gross section area (in²)
    Ig         : float – gross moment of inertia (in⁴)
    e_cgs      : float – eccentricity of CGS from centroid (in), positive below centroid
    Msw_kft    : float – self-weight moment at section (kip·ft)
    Ep         : float – strand modulus (ksi)
    Eci        : float – concrete modulus at transfer (ksi)
    N_tendons  : int   – number of tendon groups stressed sequentially

    Returns
    -------
    dfpES : float – elastic shortening loss (ksi)
    """
    if Aps <= 0 or Ag <= 0 or Ig <= 0 or Eci <= 0:
        return 0.0

    Msw = Msw_kft * 12.0  # kip·ft → kip·in

    # Factor for sequential stressing: (N-1)/(2N)
    # For single tendon (N=1), factor = 0 → ΔfpES = 0
    # Some references use N/(2(N+1)) — but AASHTO C5.9.3.2.3a uses (N-1)/(2N)
    # For post-tensioning with N=1 group, use the iterative formula directly (factor=1)
    # Actually for PT (post-tensioning), elastic shortening is computed as Ep/Eci * fcgp
    # with iterative Pi.  The (N-1)/(2N) factor applies to pretensioned beams.
    # For PT: ΔfpES = (N-1)/(2N) * Ep/Eci * fcgp, where N = # of identical tendons
    # If N=1, ΔfpES = 0 (no shortening from stressing a single tendon against itself).
    if N_tendons <= 1:
        return 0.0

    factor = (N_tendons - 1.0) / (2.0 * N_tendons)

    # Iterative: guess Pi, compute fcgp, compute ΔfpES, update Pi
    Pi = fp_avg * Aps  # initial guess
    dfpES = 0.0
    for _ in range(10):
        fcgp = Pi / Ag + Pi * e_cgs ** 2 / Ig - Msw * e_cgs / Ig
        dfpES_new = factor * (Ep / Eci) * max(fcgp, 0.0)
        Pi = (fp_avg - dfpES_new) * Aps
        if abs(dfpES_new - dfpES) < 0.001:
            break
        dfpES = dfpES_new

    return max(dfpES, 0.0)


# ---------------------------------------------------------------------------
# 7. Time-dependent losses  (AASHTO 5.9.3.3 Approximate)
# ---------------------------------------------------------------------------

def time_dependent_loss(fpi, Aps, Ag, H_pct, fci):
    """Compute approximate time-dependent loss ΔfpLT per AASHTO 5.9.3.3.

    Parameters
    ----------
    fpi   : float – average prestress immediately after transfer (ksi)
    Aps   : float – total strand area (in²)
    Ag    : float – gross section area (in²)
    H_pct : float – average ambient relative humidity (%)
    fci   : float – concrete strength at transfer (ksi)

    Returns
    -------
    dfpLT : float – total long-term loss (ksi)
    """
    if Aps <= 0 or Ag <= 0 or fci <= 0:
        return 0.0

    gamma_h = 1.7 - 0.01 * H_pct
    gamma_st = 5.0 / (1.0 + fci)
    delta_fpR = 2.4  # ksi — relaxation loss

    dfpLT = 10.0 * fpi * (Aps / Ag) * gamma_h * gamma_st + 12.0 * gamma_h * gamma_st + delta_fpR
    return max(dfpLT, 0.0)


# ---------------------------------------------------------------------------
# 8. Compute full profile
# ---------------------------------------------------------------------------

def compute_full_profile(inputs):
    """Master function: build tendon geometry + compute all losses.

    Parameters
    ----------
    inputs : dict with keys:
        spans       : list of {L_ft, y_left, y_mid, y_right}
        fpj         : float – jacking stress (ksi)
        jack_end    : str   – "left", "right", or "both"
        mu          : float – friction coefficient
        kappa       : float – wobble coefficient (per ft)
        delta_set   : float – anchor set (in)
        Ep          : float – strand modulus (ksi), typically 28500
        Aps         : float – total strand area (in²)
        Ag          : float – gross section area (in²)
        Ig          : float – gross moment of inertia (in⁴)
        yb          : float – distance from top to centroid (in)
        Msw         : float – self-weight moment at midspan (kip·ft)
        Eci         : float – concrete modulus at transfer (ksi)
        N_tendons   : int   – number of tendon groups
        H           : float – relative humidity (%)
        fci         : float – concrete strength at transfer (ksi)

    Returns
    -------
    result : dict with keys:
        profile       : list of {x_ft, y, dp, theta_deg, fp_friction_left, fp_friction_right,
                                  fp_after_set, fpe, P_eff, Vp}
        loss_summary  : dict
    """
    spans = inputs["spans"]
    fpj = inputs["fpj"]
    jack_end = inputs.get("jack_end", "both")
    mu = inputs["mu"]
    kappa = inputs["kappa"]
    delta_set = inputs["delta_set"]
    Ep = inputs.get("Ep", 28500.0)
    Aps = inputs.get("Aps", 0.0)
    h_section = inputs.get("h_section", 0.0)  # section depth for dp clamping
    Ag = inputs.get("Ag", 1.0)
    Ig = inputs.get("Ig", 1.0)
    yb = inputs.get("yb", 0.0)  # centroid from top
    Msw = inputs.get("Msw", 0.0)
    Eci = inputs.get("Eci", 4000.0)
    N_tendons = inputs.get("N_tendons", 1)
    H = inputs.get("H", 70.0)
    fci = inputs.get("fci", 4.0)

    # --- Step 1: Build geometry ---
    prof = build_tendon_profile(spans)

    # --- Step 2: Friction losses ---
    fp_left, fp_right = friction_loss(fpj, mu, kappa, prof)

    # --- Step 3: Anchor set ---
    if jack_end in ("left", "both"):
        fp_left_set, x_set_left = anchor_set_loss(fp_left, prof, delta_set, Ep)
    else:
        fp_left_set = [0.0] * len(prof)
        x_set_left = 0.0

    if jack_end in ("right", "both"):
        fp_right_set, x_set_right = anchor_set_loss_right(fp_right, prof, delta_set, Ep)
    else:
        fp_right_set = [0.0] * len(prof)
        x_set_right = 0.0

    # --- Step 4: Envelope ---
    if jack_end == "both":
        fp_immediate = dual_end_envelope(fp_left_set, fp_right_set)
    elif jack_end == "left":
        fp_immediate = fp_left_set
    else:
        fp_immediate = fp_right_set

    # --- Step 5: Elastic shortening ---
    fp_avg = sum(fp_immediate) / len(fp_immediate) if fp_immediate else fpj
    # Eccentricity at midspan (use profile midpoint)
    mid_idx = len(prof) // 2
    e_cgs = prof[mid_idx]["y"] - yb if yb > 0 else 0.0  # positive = below centroid
    dfpES = elastic_shortening(fp_avg, Aps, Ag, Ig, e_cgs, Msw, Ep, Eci, N_tendons)

    # --- Step 6: Time-dependent losses ---
    fpi = fp_avg - dfpES  # prestress immediately after transfer
    dfpLT = time_dependent_loss(fpi, Aps, Ag, H, fci)

    # --- Step 7: Final profile ---
    total_loss_uniform = dfpES + dfpLT
    result_profile = []
    fpe_values = []
    for i, pt in enumerate(prof):
        fpe = max(fp_immediate[i] - total_loss_uniform, 0.0)
        P_eff = fpe * Aps
        Vp = abs(P_eff * math.sin(pt["theta"]))  # Always positive per AASHTO (acts against gravity shear)
        dp = pt["y"]  # CGS depth from top = dp
        if h_section > 0:
            dp = max(0.0, min(dp, h_section))  # clamp to section bounds
        fpe_values.append(fpe)
        result_profile.append({
            "x_ft": round(pt["x_ft"], 4),
            "y": round(pt["y"], 4),
            "dp": round(dp, 4),
            "theta_deg": round(math.degrees(pt["theta"]), 4),
            "fp_friction_left": round(fp_left[i], 4),
            "fp_friction_right": round(fp_right[i], 4),
            "fp_left_after_set": round(fp_left_set[i], 4),
            "fp_right_after_set": round(fp_right_set[i], 4),
            "fp_immediate": round(fp_immediate[i], 4),
            "fpe": round(fpe, 4),
            "P_eff": round(P_eff, 4),
            "Vp": round(Vp, 4),
        })

    # --- Step 8: Loss summary ---
    avg_friction_left = fpj - (sum(fp_left) / len(fp_left)) if fp_left else 0.0
    avg_friction_right = fpj - (sum(fp_right) / len(fp_right)) if fp_right else 0.0
    # Only compute anchor set loss for ends that are actually jacked
    if jack_end in ("left", "both"):
        avg_set_loss_left = (sum(fp_left) / len(fp_left)) - (sum(fp_left_set) / len(fp_left_set)) if fp_left else 0.0
    else:
        avg_set_loss_left = 0.0
    if jack_end in ("right", "both"):
        avg_set_loss_right = (sum(fp_right) / len(fp_right)) - (sum(fp_right_set) / len(fp_right_set)) if fp_right else 0.0
    else:
        avg_set_loss_right = 0.0
    fpe_min = min(fpe_values) if fpe_values else 0.0
    fpe_max = max(fpe_values) if fpe_values else 0.0
    fpe_avg = sum(fpe_values) / len(fpe_values) if fpe_values else 0.0

    loss_summary = {
        "fpj": round(fpj, 2),
        "avg_friction_loss_left": round(avg_friction_left, 2),
        "avg_friction_loss_right": round(avg_friction_right, 2),
        "avg_anchor_set_loss_left": round(avg_set_loss_left, 2),
        "avg_anchor_set_loss_right": round(avg_set_loss_right, 2),
        "elastic_shortening": round(dfpES, 2),
        "time_dependent": round(dfpLT, 2),
        "total_loss_uniform": round(total_loss_uniform, 2),
        "fpe_min": round(fpe_min, 2),
        "fpe_max": round(fpe_max, 2),
        "fpe_avg": round(fpe_avg, 2),
        "x_set_left_ft": round(x_set_left, 2),
        "x_set_right_ft": round(x_set_right, 2),
        "jack_end": jack_end,
        # Additional data for detailed report
        "mu": mu,
        "kappa": kappa,
        "delta_set_in": delta_set,
        "Ep": Ep,
        "Aps": Aps,
        "Ag": round(Ag, 2),
        "Ig": round(Ig, 1),
        "yb": round(yb, 2),
        "Msw": round(Msw, 2),
        "Eci": round(Eci, 1),
        "N_tendons": N_tendons,
        "H": H,
        "fci": round(fci, 2),
        "fp_avg_before_ES": round(fp_avg, 2),
        "e_cgs": round(e_cgs, 2),
        "fpi": round(fpi, 2),
        "total_angle_rad": round(sum(abs(p["theta"]) for p in prof) * 0.5 if prof else 0, 4),
        "L_total_ft": round(prof[-1]["x_ft"], 2) if prof else 0,
        "gamma_h": round(1.7 - 0.01 * H, 4),
        "gamma_st": round(5.0 / (1.0 + fci), 4),
    }

    return {"profile": result_profile, "loss_summary": loss_summary}


# ---------------------------------------------------------------------------
# 9. Helper: interpolate from profile at arbitrary x
# ---------------------------------------------------------------------------

def interpolate_at_x(profile, x_ft, key):
    """Linearly interpolate a profile value at a given x_ft.

    Parameters
    ----------
    profile : list of dict – from compute_full_profile result["profile"]
    x_ft    : float – location along beam (ft)
    key     : str – field to interpolate ("fpe", "Vp", "dp", etc.)

    Returns
    -------
    float – interpolated value, or None if x_ft is out of range
    """
    if not profile:
        return None
    if x_ft <= profile[0]["x_ft"]:
        return profile[0][key]
    if x_ft >= profile[-1]["x_ft"]:
        return profile[-1][key]
    # Binary search for bracket
    lo, hi = 0, len(profile) - 1
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if profile[mid]["x_ft"] <= x_ft:
            lo = mid
        else:
            hi = mid
    # Linear interpolation
    x0, x1 = profile[lo]["x_ft"], profile[hi]["x_ft"]
    v0, v1 = profile[lo][key], profile[hi][key]
    if abs(x1 - x0) < 1e-12:
        return v0
    frac = (x_ft - x0) / (x1 - x0)
    return v0 + frac * (v1 - v0)
