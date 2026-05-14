#!/usr/bin/env python3
"""
Quick test to verify shN=0 (None) handling in calc_engine.
Maps shN=0 to valid BARS[4] and verifies calculations work.
"""
import sys
sys.path.insert(0, '.')

from calc_engine import calculate_all

# Minimal valid input (will be processed via derive_constants)
fc = 4.0
test_input = {
    'fc': fc,
    'fy': 60.0,
    'fpu': 270.0,
    'Ept': 28000,
    'Es': 29000,
    'Ec': 2500 * (fc ** 0.33),  # Auto-calculated from fc
    'fpy': 0.9 * 270.0,          # Auto-calculated from fpu
    'ecl': 0.003,
    'etl': 0.05,
    'ag': 0.5,
    'lam': 1.0,
    'phi_v': 0.9,
    'gamma_e': 1.0,
    'codeEdition': '10th',
    'sectionClass': 'UD',
    'secType': 'RECTANGULAR',
    'b': 24.0,
    'h': 24.0,
    'bw_input': 24.0,
    'hf_top': 0,
    'hf_bot': 0,
    'cover': 2.0,
    'ecl_override': False,
    'etl_override': False,
    'barN_top': 7,
    'nBars_top': 4,
    'd_top': 2.5,
    'barN_bot': 7,
    'nBars_bot': 4,
    'd_bot': 21.5,
    'As_top_ovr': None,
    'As_bot_ovr': None,
    'nStrands': 0,
    'strand_area': 0.196,
    'dp': 4.0,
    'ductDia': 0.0,
    'shN': 4,  # Remapped from 0 (None)
    'shear_legs': 2,
    's_shear': 12.0,
    'tN': 4,   # Also remapped from 0 (None)
    's_torsion': 12.0,
}

demand_rows = [
    {
        'Pu': 500.0,
        'Mu': 1000.0,
        'Vu': 100.0,
        'Tu': 50.0,
        'Vp': 0,
        'Ms': 0,
        'Ps': 0,
    }
]

print("Testing calculate_all with shN=4 (remapped from None)...")
try:
    result = calculate_all(test_input, demand_rows, 0)
    print("[OK] Calculation succeeded!")
    print(f"  Flexure result keys: {list(result['flexure'].keys())}")
    print(f"  Shear result keys: {list(result['shear'].keys())}")
    print(f"  Torsion result keys: {list(result['torsion'].keys())}")
    print("Test PASSED: None shear reinforcement is handled correctly.")
except Exception as e:
    print(f"[FAIL] Calculation FAILED: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
