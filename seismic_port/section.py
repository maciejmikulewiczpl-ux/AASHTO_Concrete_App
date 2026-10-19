"""Circular reinforced-concrete section: geometry, reinforcement and fibres.

A :class:`CircularSection` bundles the geometry, longitudinal and transverse
reinforcement, and material models, and exposes a fibre discretisation used by
the moment-curvature solver.  The same class represents both the column and the
Type II shaft.

Pure-Python port of seismic_column/section.py (upstream commit 9265d67):
numpy arrays are replaced by lists.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math

from .materials import (
    BAR_PROPERTIES,
    ConfinedConcrete,
    ReinforcingSteel,
    UnconfinedConcrete,
    bar_area,
    bar_diameter,
)


@dataclass
class CircularSection:
    """Circular RC section with spiral/hoop confinement.

    Parameters
    ----------
    D:
        Overall diameter, in.
    fc:
        Specified (nominal) concrete strength f'c, ksi.  Used for the shear and
        detailing provisions, which are written on nominal strength.
    fce_factor:
        Multiplier giving the *expected* strength f'ce = factor * f'c used for
        the section response (moment-curvature).  AASHTO SGS 8.4.4-1 requires
        f'ce >= 1.3 f'c; set to 1.0 to model on nominal strength.
    cover:
        Clear cover to the transverse steel, in.
    n_bars:
        Number of longitudinal bars (equally spaced on a circle).
    long_bar_no:
        Longitudinal bar designation.
    spiral_bar_no:
        Transverse (spiral/hoop) bar designation.
    spiral_spacing:
        Centre-to-centre pitch of the transverse steel, in.
    fye, fue:
        Expected yield / ultimate stress of longitudinal steel, ksi.
    fyh:
        Expected yield stress of transverse steel, ksi.
    hoops:
        ``True`` for discrete circular hoops, ``False`` for continuous spiral.
    n_strips:
        Number of horizontal concrete fibres for the discretisation.
    """

    D: float = 48.0
    fc: float = 4.0
    fce_factor: float = 1.3
    fce_floor: float | None = None
    cover: float = 2.0
    n_bars: int = 20
    long_bar_no: int = 10
    spiral_bar_no: int = 5
    spiral_spacing: float = 3.0
    fye: float = 68.0
    fue: float = 95.0
    fyh: float = 68.0
    hoops: bool = False
    long_bundle: int = 1
    spiral_bundle: int = 1
    n_strips: int = 120

    # derived geometry / materials
    Ag: float = field(init=False)
    fce: float = field(init=False)          # expected strength, ksi
    Ast: float = field(init=False)
    rho_l: float = field(init=False)
    ds: float = field(init=False)          # core diameter to spiral centreline
    Acore: float = field(init=False)
    rho_s: float = field(init=False)
    r_bars: float = field(init=False)      # radius to longitudinal bar centreline
    confined: ConfinedConcrete = field(init=False)
    unconfined: UnconfinedConcrete = field(init=False)
    steel: ReinforcingSteel = field(init=False)

    def __post_init__(self) -> None:
        dbl = bar_diameter(self.long_bar_no)
        dsp = bar_diameter(self.spiral_bar_no)
        self.Ag = math.pi * self.D ** 2 / 4.0
        # SGS 8.4.4-1 / 8.5: section response uses the *expected* strength.
        # Caltrans SDC 3.3.6-4 additionally floors f'ce at 5.0 ksi.
        self.fce = self.fce_factor * self.fc
        if self.fce_floor is not None:
            self.fce = max(self.fce, self.fce_floor)
        self.Ast = self.n_bars * self.long_bundle * bar_area(self.long_bar_no)
        self.rho_l = self.Ast / self.Ag
        self.ds = self.D - 2.0 * self.cover - dsp
        self.Acore = math.pi * self.ds ** 2 / 4.0
        self.r_bars = self.D / 2.0 - self.cover - dsp - dbl / 2.0

        rho_long_core = self.Ast / self.Acore
        self.confined = ConfinedConcrete(
            fc=self.fce,
            D=self.D,
            cover=self.cover,
            spiral_bar_no=self.spiral_bar_no,
            spacing=self.spiral_spacing,
            fyh=self.fyh,
            rho_long=rho_long_core,
            hoops=self.hoops,
            spiral_bundle=self.spiral_bundle,
        )
        self.rho_s = self.confined.rho_s
        self.unconfined = UnconfinedConcrete(fc=self.fce)
        self.steel = ReinforcingSteel(bar_no=self.long_bar_no, fye=self.fye, fue=self.fue)

    # ------------------------------------------------------------------
    # Fibre discretisation
    # ------------------------------------------------------------------
    def concrete_fibres(self) -> tuple[list[float], list[float], list[float]]:
        """Return (y, area_confined, area_unconfined) for horizontal strips.

        ``y`` is the strip-centroid height measured from the section centroid
        (positive up).  ``area_confined`` is the strip area inside the confined
        core; ``area_unconfined`` is the remaining (cover) area of the strip.
        """
        R = self.D / 2.0
        Rc = self.ds / 2.0
        n = self.n_strips
        step = (2.0 * R) / n
        edges = [-R + i * step for i in range(n)] + [R]  # == np.linspace(-R, R, n + 1)
        y = [0.5 * (edges[i] + edges[i + 1]) for i in range(n)]
        h = edges[1] - edges[0]

        area_confined: list[float] = []
        area_unconfined: list[float] = []
        for yi in y:
            half_full = math.sqrt(max(R ** 2 - yi ** 2, 0.0)) if abs(yi) < R else 0.0
            half_core = math.sqrt(max(Rc ** 2 - yi ** 2, 0.0)) if abs(yi) < Rc else 0.0
            area_full = 2.0 * half_full * h
            area_core = 2.0 * half_core * h
            area_confined.append(area_core)
            area_unconfined.append(max(area_full - area_core, 0.0))
        return y, area_confined, area_unconfined

    def steel_fibres(self) -> tuple[list[float], list[float]]:
        """Return (y, area) for the longitudinal bars around the circle."""
        n = self.n_bars
        angles = [i * (2.0 * math.pi / n) for i in range(n)]  # == np.linspace(0, 2pi, n, endpoint=False)
        y = [self.r_bars * math.sin(a) for a in angles]
        area = [bar_area(self.long_bar_no) * self.long_bundle] * n
        return y, area

    # ------------------------------------------------------------------
    # Convenience
    def gross_inertia(self) -> float:
        """Gross moment of inertia of the concrete section, in^4."""
        return math.pi * self.D ** 4 / 64.0

    def transverse_area(self) -> float:
        """Total area of transverse steel at one layer (incl. bundling), in^2."""
        return BAR_PROPERTIES[self.spiral_bar_no]["area"] * self.spiral_bundle
