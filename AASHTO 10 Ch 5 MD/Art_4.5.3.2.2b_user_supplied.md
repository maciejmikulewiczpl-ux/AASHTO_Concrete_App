# AASHTO LRFD BDS 10th Ed. (2024): Art. 4.5.3.2.2b and Table C4.6.2.5-1 (user-supplied)

Transcribed verbatim from page images the user supplied on 2026-10-19 (p. 4-15/4-16 and Table C4.6.2.5-1). This is the only source
the column-on-shaft moment-magnification code may cite for these provisions (CLAUDE.md citation rule).

## 4.5.3.2.2b—Moment Magnification—Beam Columns

The factored moments or stresses may be increased to reflect effects of deformations as follows:

- Mc = δb·M2b + δs·M2s  (4.5.3.2.2b-1)
- fc = δb·f2b + δs·f2s  (4.5.3.2.2b-2)

in which:

- δb = Cm / (1 − Pu/(φK·Pe)) ≥ 1.0  (4.5.3.2.2b-3)
- δs = 1 / (1 − ΣPu/(φK·ΣPe))  (4.5.3.2.2b-4)

where:

- Mc = factored moment, corrected to account for second-order effects (kip-ft)
- M2b = moment on compression member due to factored gravity loads that result in no appreciable sidesway calculated by conventional
  first-order elastic frame analysis; always positive (kip-ft)
- M2s = moment on compression member due to factored lateral or gravity loads that result in sidesway, Δ, greater than ℓu/1,500,
  calculated by conventional first-order elastic frame analysis; always positive (kip-ft)
- fc = factored stress, corrected to account for second-order effects (ksi)
- f2b = stress corresponding to M2b (ksi)
- f2s = stress corresponding to M2s (ksi)
- Pu = factored axial load (kip)
- φK = stiffness reduction factor; 0.75 for concrete members and 1.0 for steel, concrete-filled steel tubes, and aluminum members
- Pe = Euler buckling load (kip)

For steel/concrete composite columns, the Euler buckling load, Pe, shall be determined as specified in Article 6.9.5.1. For all other
cases, Pe shall be taken as:

- Pe = π²·EI / (K·ℓu)²  (4.5.3.2.2b-5)

where:

- E = modulus of elasticity (ksi)
- I = moment of inertia about axis under consideration (in.⁴)
- K = effective length factor in the plane of bending as specified in Article 4.6.2.5. For calculation of δb, Pe shall be based on the
  K-factor for braced frames; for calculation of δs, Pe shall be based on the K-factor for unbraced frames
- ℓu = unsupported length of a compression member (in.)

For concrete compression members, the provisions of Article 5.6.4.3 also apply.

For members braced against sidesway, δs shall be taken as 1.0 unless analysis indicates that a lower value may be used. For members not
braced against sidesway, δb shall be determined as for a braced member and δs for an unbraced member.

For members braced against sidesway and without transverse loads between supports, the moment gradient coefficient, Cm, may be taken as:

- Cm = 0.6 + 0.4·(M1b/M2b)  (4.5.3.2.2b-6)

where:

- M1b = smaller factored end moment
- M2b = larger factored end moment

The ratio M1b/M2b is considered positive if the component is bent in single curvature and negative if it is bent in double curvature.

For all other cases, Cm shall be taken as 1.0.

In structures that are not braced against sidesway, the flexural members and foundation units framing into the compression member shall be
designed for the sum of end moments of the compression member at the joint.

Where compression members are subject to flexure about both principal axes, the moment about each axis shall be magnified by δ, determined
from the corresponding conditions of restraint about that axis.

Where a group of compression members on one level comprise a bent, or where they are connected integrally to the same superstructure, and
collectively resist the sidesway of the structure, the value of δs shall be computed for the member group with ΣPu and ΣPe equal to the
summations for all columns in the group.

Commentary (right column, same page): "The previous limit Cm ≥ 0.4 has been shown to be unnecessary in AISC (1994), Chapter C commentary."

## Table C4.6.2.5-1—Effective Length Factors, K

| Case | Buckled shape (end conditions, bottom / top) | Theoretical K | Design value of K when ideal conditions are approximated |
|---|---|---|---|
| (a) | rotation fixed, translation fixed / rotation fixed, translation fixed | 0.5 | 0.65 |
| (b) | rotation free, translation fixed / rotation fixed, translation fixed | 0.7 | 0.80 |
| (c) | rotation free, translation fixed / rotation free, translation fixed | 1.0 | 1.0 |
| (d) | rotation fixed, translation fixed / rotation fixed, translation free | 1.0 | 1.2 |
| (e) | rotation fixed, translation fixed / rotation free, translation free | 2.0 | 2.1 |
| (f) | rotation free, translation fixed / rotation fixed, translation free | 2.0 | 2.0 |

End condition codes (as printed): rotation fixed + translation fixed; rotation free + translation fixed; rotation fixed + translation
free; rotation free + translation free. (The bottom/top reading of cases (a)–(f) follows the sketches: the bottom is the lower support
symbol and the top is the upper one.)

## §5.6.4.3 EI equations (user-supplied image, 2026-10-19; missing from the Chapter 5 Markdown)

In lieu of a more precise calculation, EI for use in determining Pe, as specified in Eq. 4.5.3.2.2b-5, shall be determined as the larger
of the following:

- EI = (Ec·Ig/5 + Es·Is) / (1 + βd)  (5.6.4.3-1)
- EI = (Ec·Ig/2.5) / (1 + βd)  (5.6.4.3-2)

where:

- EI = flexural stiffness (kip-in.²)
- Ec = modulus of elasticity of concrete (ksi)
- Ig = moment of inertia of the gross concrete section about the centroidal axis, neglecting the reinforcement (in.⁴)
- Es = modulus of elasticity of longitudinal steel (ksi)
- Is = moment of inertia of longitudinal reinforcement about the centroidal axis (in.⁴)
- βd = ratio of maximum factored permanent load moments to maximum factored total load moment; always positive

For eccentrically prestressed members, consideration shall be given to the effect of lateral deflection due to prestressing in determining
the magnified moment.
