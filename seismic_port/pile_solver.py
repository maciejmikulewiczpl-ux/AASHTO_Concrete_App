"""Finite-element lateral pile (beam-on-nonlinear-Winkler) solver.

Pure-Python port (no numpy/scipy) of seismic-column@9265d67 pile_solver.py, plus
``_cached_pile_solve`` / ``inground_demand`` from sdc_capacity.py.
``scipy.linalg.solve_banded`` is replaced by :func:`_solve_banded` (banded
Gaussian elimination with partial pivoting, LAPACK ``gbsv``-style), and numpy
arrays by lists.

Models the **column and shaft as one continuous Euler–Bernoulli beam-column**:
the column segment above ground (rigidity ``EI_col``, no soil) and the embedded
shaft below (``EI_shaft``, nonlinear p-y soil springs). A lateral point load
``V`` is applied at the **column top** — the moment at the top of shaft,
``M = V·Hcol``, and the resulting shaft deflection therefore include *both* the
shear and the column overturning moment (the beam is continuous).

The nonlinear p-y springs (:mod:`seismic_port.soil`) are handled by **secant
iteration**: each pass updates the nodal lateral spring from the p-y secant
modulus ``Es = p/y`` at the current deflection, until the deflection converges.
Axial load enters through the consistent **geometric stiffness** (P-Δ).

Units: kip, inch throughout (EI kip-in², loads kip, deflection in, moment
kip-in). Axial load ``axial`` is COMPRESSION-POSITIVE (upstream convention).
The solver returns the pile-head flexibility/stiffness, the deflection
and moment profiles, the max in-ground shaft moment, and an equivalent
depth-to-fixity ``Df_eq`` matching the two-segment cantilever.

Head-moment sign (upstream behaviour, verified against its tests): the
fixed-fixed member is solved with ``V_head = 2*Mo/Hcol`` and ``M_head = +Mo``,
which puts ``Mo`` at the ground line; ``M_head = -Mo`` would put ``3*Mo`` there.
(Upstream's ``solve_lateral`` docstring says ``-Mp``; its caller
``sdc_capacity`` and test_two_direction use ``+Mo``.)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Dict, List, Optional

from .soil import SoilProfile

_BW = 3   # half-bandwidth of the 2-DOF Euler-Bernoulli beam global matrix


class LinAlgError(Exception):
    """Singular banded system (stands in for ``numpy.linalg.LinAlgError``)."""


def _solve_banded(ab, b, bw: int = _BW) -> List[float]:
    """Solve ``K x = b`` for a banded ``K`` given as ``ab[bw + i - j][j] = K[i][j]``.

    Same storage and result as ``scipy.linalg.solve_banded((bw, bw), ab, b)``:
    Gaussian elimination with partial (row) pivoting, so the upper factor's
    bandwidth grows to ``2*bw`` (LAPACK ``gbtrf``).  An exactly-zero pivot raises
    :class:`LinAlgError` ("singular matrix"), as LAPACK/scipy do.  The matrix
    need not be positive-definite (P-Δ can make it indefinite).  ``ab`` and
    ``b`` are not modified.
    """
    n = len(b)
    A = [[0.0] * n for _ in range(n)]
    for j in range(n):
        for i in range(max(0, j - bw), min(n, j + bw + 1)):
            A[i][j] = ab[bw + i - j][j]
    x = [float(v) for v in b]
    for k in range(n):
        last = min(n - 1, k + bw)
        p, amax = k, abs(A[k][k])
        for r in range(k + 1, last + 1):          # first max |a_rk| (idamax)
            a = abs(A[r][k])
            if a > amax:
                p, amax = r, a
        if amax == 0.0:
            raise LinAlgError("singular matrix")
        if p != k:
            A[p], A[k] = A[k], A[p]
            x[p], x[k] = x[k], x[p]
        rowk = A[k]
        piv = rowk[k]
        jend = min(n, k + 2 * bw + 1)
        xk = x[k]
        for r in range(k + 1, last + 1):
            Ar = A[r]
            f = Ar[k]
            if f != 0.0:
                f /= piv
                Ar[k] = 0.0
                for j in range(k + 1, jend):
                    Ar[j] -= f * rowk[j]
                x[r] -= f * xk
    for k in range(n - 1, -1, -1):
        rowk = A[k]
        s = x[k]
        for j in range(k + 1, min(n, k + 2 * bw + 1)):
            s -= rowk[j] * x[j]
        x[k] = s / rowk[k]
    return x


@dataclass
class PileSolution:
    x: List[float]              # distance from column top, in (0 = top)
    y: List[float]              # lateral deflection, in
    moment: List[float]         # bending moment, kip-in
    shear: List[float]          # shear V = dM/dx, kip
    ground_index: int           # first node at/below ground (top of shaft)
    head_deflection: float      # y at the column top, in
    head_stiffness: float       # V / y_top, kip/in
    head_flexibility: float     # y_top / V, in/kip
    Df_eq: float                # equivalent depth to fixity below top of shaft, in
    max_inground_moment: float  # max |M| below ground, kip-in
    max_moment_depth: float     # its depth below top of shaft, in
    converged: bool
    iterations: int
    stable: bool = True         # physical solution (positive, bounded deflection)
    max_inground_shear: float = 0.0   # max |V| below ground, kip


def _ke_elastic(EI: float, L: float) -> List[List[float]]:
    """Euler–Bernoulli elastic 4x4 stiffness, DOF [v_i, θ_i, v_j, θ_j]."""
    L2, L3 = L * L, L * L * L
    c = EI / L3
    m = [
        [12.0,   6*L,  -12.0,   6*L],
        [6*L,  4*L2,   -6*L,  2*L2],
        [-12.0, -6*L,   12.0,  -6*L],
        [6*L,  2*L2,   -6*L,  4*L2],
    ]
    return [[c * v for v in row] for row in m]


def _element_matrices(EI: float, L: float, P: float) -> List[List[float]]:
    """Elastic + geometric (P-Δ) stiffness; compression (P>0) softens laterally."""
    L2 = L * L
    c = P / (30.0 * L)
    kg = [
        [36.0,   3*L,  -36.0,   3*L],
        [3*L,  4*L2,   -3*L,  -L2],
        [-36.0, -3*L,   36.0,  -3*L],
        [3*L,  -L2,   -3*L,  4*L2],
    ]
    ke = _ke_elastic(EI, L)
    return [[ke[a][b] - c * kg[a][b] for b in range(4)] for a in range(4)]


def _linspace(start: float, stop: float, num: int) -> List[float]:
    """``numpy.linspace(start, stop, num)`` (endpoint included, exact stop)."""
    if num == 1:
        return [float(start)]
    step = (stop - start) / (num - 1)
    out = [start + i * step for i in range(num)]
    out[-1] = float(stop)
    return out


def solve_lateral(
    Hcol: float,
    L_embed: float,
    EI_col: float,
    EI_shaft: float,
    D_shaft: float,
    axial: float,
    soil: SoilProfile,
    V_head: float,
    *,
    M_head: float = 0.0,
    head_fixed: bool = False,
    target_h: Optional[float] = None,
    max_nodes: int = 241,
    max_iter: int = 100,
    tol: float = 1e-6,
    relax: float = 1.0,
) -> PileSolution:
    """Solve the laterally-loaded column+shaft and return a :class:`PileSolution`.

    ``V_head`` is the lateral load at the column top (use ``Mp/Hcol`` for the
    effective/secant head stiffness at yield). ``target_h`` sets the element
    length (default ≈ D_shaft/4, capped by ``max_nodes``).

    ``M_head`` is an applied MOMENT at the column top, zero by default — which
    is the free-head cantilever this has always solved.  It exists for the
    fixed-fixed member, whose deck end carries moment.  Pass
    ``V_head = 2*Mo/Hcol`` with ``M_head = +Mo`` to land ``Mo`` at the
    interface (see the module docstring for the sign; ``-Mo`` gives ``3*Mo``).
    """
    L_total = Hcol + L_embed
    h_t = target_h if target_h else max(D_shaft / 4.0, L_total / (max_nodes - 1))
    # mesh with a node EXACTLY at the ground line (Hcol): separate column & shaft
    # meshes sharing that node, so the diagrams and the interface moment are clean
    n_col = max(int(round(Hcol / h_t)), 2) if Hcol > 0 else 0
    budget = max_nodes - 1 - n_col
    n_shaft = max(min(int(round(L_embed / h_t)), budget), 10)
    x_col = _linspace(0.0, Hcol, n_col + 1) if n_col else [0.0]
    x_shaft = _linspace(Hcol, L_total, n_shaft + 1)[1:]
    x = x_col + x_shaft
    n_node = len(x)
    n_elem = n_node - 1
    ndof = 2 * n_node

    ground_index = n_col                             # the node at Hcol
    depth = [max(xi - Hcol, 0.0) for xi in x]        # depth below top of shaft
    embedded = [xi >= Hcol - 1e-9 for xi in x]
    he = [x[i + 1] - x[i] for i in range(n_elem)]    # per-element length, in
    # nodal tributary length = half of each adjacent element
    trib = [0.0] * n_node
    for i in range(n_elem):
        trib[i] += 0.5 * he[i]
        trib[i + 1] += 0.5 * he[i]

    EI_elem = [EI_col if e < max(n_col, 0) else EI_shaft for e in range(n_elem)]

    # pre-assemble the constant elastic + geometric global matrix in banded form
    # (ab[_BW + i - j][j] = K[i][j]); only the soil-spring diagonal changes per pass
    ab0 = [[0.0] * ndof for _ in range(2 * _BW + 1)]
    for e in range(n_elem):
        ke = _element_matrices(EI_elem[e], he[e], axial)
        d = (2 * e, 2 * e + 1, 2 * e + 2, 2 * e + 3)
        for a, ia in enumerate(d):
            for b, jb in enumerate(d):
                ab0[_BW + ia - jb][jb] += ke[a][b]
    F = [0.0] * ndof
    F[0] = V_head                                     # lateral load at column top
    F[1] = M_head                                     # ... and moment there (DOF 1
    #                                                   is the head rotation; 0 =
    #                                                   free head, as it always was)
    # A FIXED head restrains the rotation instead of loading it, so the head
    # moment becomes a reaction rather than an input.  Penalty on the DOF-1
    # diagonal, scaled off the assembled matrix so it dominates at any EI.
    head_penalty = (1.0e10 * max(abs(v) for v in ab0[_BW]) if head_fixed
                    else 0.0)
    if head_fixed:
        F[1] = 0.0
    spring_dofs = [2 * i for i in range(n_node) if embedded[i]]
    spring_depth = [depth[i] for i in range(n_node) if embedded[i]]
    spring_trib = [trib[i] for i in range(n_node) if embedded[i]]

    v = [0.0] * n_node
    u = [0.0] * ndof
    converged = False
    prev_dv = math.inf
    runaway = 20.0 * L_total          # deflection beyond this = clearly unstable
    stall = 0                         # consecutive non-improving iterations
    it = 0
    for it in range(1, max_iter + 1):
        diag = list(ab0[_BW])
        diag[1] += head_penalty                       # 0.0 unless head_fixed
        for dof, zc, tb in zip(spring_dofs, spring_depth, spring_trib):
            Es = soil.secant_modulus(zc, v[dof // 2], D_shaft)      # kip/in^2
            diag[dof] += Es * tb                                     # lateral spring
        ab = list(ab0)
        ab[_BW] = diag
        # A P-Δ / very-soft-soil candidate can drive Ke - Kg to (near-)singular.
        # The solve then raises LinAlgError (or returns inf/nan). Treat that as
        # an UNSTABLE analysis — the physicality guard below yields the flexible
        # sentinel — rather than letting it crash the whole batch row.
        try:
            u_new = _solve_banded(ab, F, _BW)
        except LinAlgError:
            break
        if not all(math.isfinite(t) for t in u_new):
            break
        u = u_new
        v_new = u[0::2]
        dv = max(abs(a - b) for a, b in zip(v_new, v))
        # Early bail-outs for the (common, expensive) UNSTABLE cases — a soft
        # bound that P-Δ-buckles or oscillates would otherwise burn all max_iter
        # secant passes only to be flagged unstable anyway.  Both leave
        # converged=False, so the physicality guard returns the flexible sentinel.
        if max(abs(t) for t in v_new) > runaway:     # deflection running away
            break
        stall = stall + 1 if dv >= prev_dv else 0
        if stall >= 12:                                # not converging (oscillating)
            break
        # divergence guard: back off the step if the update grows
        r = relax if dv <= prev_dv else max(relax * 0.5, 0.2)
        v = [r * a + (1.0 - r) * b for a, b in zip(v_new, v)]
        prev_dv = dv
        if dv / max(max(abs(t) for t in v), 1e-9) < tol:
            v = v_new
            converged = True
            break

    theta = u[1::2]
    # moment & shear from the FE element end-forces (EI-consistent, so the
    # column/shaft rigidity change at the ground line is handled correctly —
    # the internal moment stays continuous there).
    moment = [0.0] * n_node
    shear = [0.0] * n_node
    wt = [0] * n_node
    for e in range(n_elem):
        k = _ke_elastic(EI_elem[e], he[e])
        de = (v[e], theta[e], v[e + 1], theta[e + 1])
        fe = [k[a][0] * de[0] + k[a][1] * de[1] + k[a][2] * de[2] + k[a][3] * de[3]
              for a in range(4)]
        # internal diagram sign: M(top)=0, M(ground)=+V*Hcol ; V(top)=+V_head
        moment[e] += -fe[1]
        moment[e + 1] += fe[3]
        shear[e] += fe[0]
        shear[e + 1] += -fe[2]
        wt[e] += 1
        wt[e + 1] += 1
    moment = [m / max(w, 1) for m, w in zip(moment, wt)]
    shear = [s / max(w, 1) for s, w in zip(shear, wt)]

    y_top = float(v[0])
    below = [dz > 0.0 for dz in depth]
    if any(below):
        idx, best = 0, -1.0
        for i in range(n_node):                       # numpy argmax: first max
            val = abs(moment[i]) if below[i] else 0.0
            if val > best:
                idx, best = i, val
        max_m = float(abs(moment[idx]))
        max_m_depth = float(depth[idx])
        max_v = float(max(abs(shear[i]) for i in range(n_node) if below[i]))
    else:
        max_m, max_m_depth, max_v = 0.0, 0.0, 0.0

    # Physicality guard: a positive load must give a positive, bounded head
    # deflection.  Soft soil (or P-Δ buckling) under a very high demand can
    # produce a negative or runaway deflection — treat that as an UNSTABLE
    # analysis (soil too soft / pile too short for the force), NOT as a stiff
    # base.  A stiff base (Df_eq -> 0) would be dangerously unconservative.
    same_sign = (V_head == 0.0) or (y_top * V_head > 0.0)
    bounded = abs(y_top) < 5.0 * L_total
    stable = bool(converged and same_sign and bounded)
    if stable and V_head != 0.0:
        f_soil = y_top / V_head
        Df_eq = equivalent_fixity_depth(
            f_soil, Hcol, EI_col, EI_shaft,
            end_fixity="fixed" if head_fixed else "free")
        head_stiff = V_head / y_top
    else:                                            # failed / unstable
        f_soil = float("inf")
        Df_eq = 50.0 * D_shaft                        # sentinel: very flexible
        head_stiff = 0.0
        stable = False

    return PileSolution(
        x=x, y=list(v), moment=moment, shear=shear, ground_index=ground_index,
        head_deflection=y_top, head_stiffness=head_stiff,
        head_flexibility=f_soil, Df_eq=Df_eq,
        max_inground_moment=max_m, max_moment_depth=max_m_depth,
        converged=converged, iterations=it, stable=stable,
        max_inground_shear=max_v,
    )


def _abc(Df: float, Hcol: float, EI_col: float, EI_shaft: float):
    """The three EI moments of the two-segment member, as in ``Geometry``."""
    L = Hcol + Df
    A = Hcol / EI_col + Df / EI_shaft
    B = Hcol ** 2 / (2.0 * EI_col) + (L ** 2 - Hcol ** 2) / (2.0 * EI_shaft)
    C = Hcol ** 3 / (3.0 * EI_col) + (L ** 3 - Hcol ** 3) / (3.0 * EI_shaft)
    return A, B, C


def equivalent_fixity_depth(f_soil: float, Hcol: float, EI_col: float,
                            EI_shaft: float, end_fixity: str = "free") -> float:
    """Depth to fixity Df below top of shaft matching the head flexibility.

    The equivalence is only meaningful against the SAME head condition the
    flexibility was measured at, which is why ``end_fixity`` is not optional
    in spirit even though it defaults to the historical free-head case:

    * ``"free"`` inverts the cantilever flexibility
      ``f = C = Hcol³/(3·EI_col) + ((Hcol+Df)³ − Hcol³)/(3·EI_shaft)``, a cubic
      in ``Hcol+Df`` and so closed-form;
    * ``"fixed"`` inverts ``f = C − B²/A``, which is not, so it is bracketed
      and bisected.  It is monotone increasing in ``Df`` — a deeper fixity is
      always more flexible — which makes the bisection safe.

    Running the free-head formula on a fixed-head flexibility is the mistake
    this parameter exists to prevent: it returns a Df far too SHALLOW (the
    applied head moment cancels much of the shear-induced head rotation, so the
    member looks stiff to a formula expecting a free head), which would read as
    a stiffer bent rather than the modelling mismatch it is.

    Returns 0 if the soil is so stiff that the column flexure alone already
    exceeds ``f_soil``.
    """
    if not math.isfinite(f_soil):
        return 0.0
    if end_fixity == "free":
        f_col = Hcol ** 3 / (3.0 * EI_col)
        if f_soil <= f_col:
            return 0.0
        # solve (Hcol+Df)^3 = Hcol^3 + 3*EI_shaft*(f_soil - f_col)
        Le = (Hcol ** 3 + 3.0 * EI_shaft * (f_soil - f_col)) ** (1.0 / 3.0)
        return max(Le - Hcol, 0.0)
    if end_fixity != "fixed":
        raise ValueError("end_fixity must be 'free' or 'fixed'")

    def flex(Df: float) -> float:
        A, B, C = _abc(Df, Hcol, EI_col, EI_shaft)
        return C - B * B / A

    if f_soil <= flex(0.0):                    # soil stiffer than the column alone
        return 0.0
    lo, hi = 0.0, max(Hcol, 1.0)
    for _ in range(60):                        # grow the bracket, then bisect
        if flex(hi) >= f_soil:
            break
        lo, hi = hi, hi * 2.0
    else:
        return hi
    for _ in range(100):
        mid = 0.5 * (lo + hi)
        if flex(mid) < f_soil:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-6 * max(hi, 1.0):
            break
    return 0.5 * (lo + hi)


# ---------------------------------------------------------------------------
# Cached p-y pile solve + in-ground demand (from upstream sdc_capacity.py)
# ---------------------------------------------------------------------------
_PILE_CACHE: Dict[tuple, PileSolution] = {}


def _cached_pile_solve(Hcol, L_embed, EI_col, EI_shaft, D_shaft, axial,
                       soil: SoilProfile, V_head, M_head: float = 0.0,
                       head_fixed: bool = False) -> PileSolution:
    # M_head MUST be in the key: a fixed-fixed solve shares every other argument
    # with the cantilever one and would otherwise collide with it in the cache.
    key = (round(Hcol, 3), round(L_embed, 3), round(EI_col, 0), round(EI_shaft, 0),
           round(D_shaft, 3), round(axial, 3), round(V_head, 3),
           round(M_head, 3), head_fixed, soil.signature())
    sol = _PILE_CACHE.get(key)
    if sol is None:
        sol = solve_lateral(Hcol, L_embed, EI_col, EI_shaft, D_shaft, axial,
                            soil, V_head, M_head=M_head,
                            head_fixed=head_fixed)
        if len(_PILE_CACHE) > 4000:
            _PILE_CACHE.clear()
        _PILE_CACHE[key] = sol
    return sol


def inground_demand(Hcol, L_embed, EI_col, EI_shaft, D_shaft, axial,
                    soil_profile: SoilProfile, V_head,
                    soil_bounds=(2.0, 0.5), M_head: float = 0.0):
    """Max below-ground shaft moment & shear at the applied head force ``V_head``.

    Runs the p-y solve over the soil-stiffness bounds (envelope) and returns
    ``(M, V, governing_solution)`` — the capacity-protection demand the shaft
    must carry ALONG ITS DEPTH.  ``M``/``V`` are 0 (and the solution ``None``)
    if every bound is unstable.  Shared by ``evaluate_column`` and the optimiser
    so both size to the identical demand.
    """
    M, V, gov = 0.0, 0.0, None
    for factor in soil_bounds:
        prof = replace(soil_profile,
                       stiffness_factor=soil_profile.stiffness_factor * factor)
        s = _cached_pile_solve(Hcol, L_embed, EI_col, EI_shaft, D_shaft, axial,
                               prof, V_head, M_head)
        if not s.stable:
            continue
        if s.max_inground_moment >= M:
            M, gov = s.max_inground_moment, s
        V = max(V, s.max_inground_shear)
    return M, V, gov
