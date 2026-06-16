"""Per-asset tick sizes. Used for price snapping and footprint cell height."""

TICK_SIZES = {
    "ES": 0.25, "NQ": 0.25, "RTY": 0.10, "YM": 1.00,
    "MES": 0.25, "MNQ": 0.25, "M2K": 0.10, "MYM": 1.00,
    "ZN": 0.015625, "ZB": 0.03125, "ZF": 0.0078125, "ZT": 0.00390625, "SR3": 0.0025,
    "CL": 0.01, "QM": 0.025, "NG": 0.001, "RB": 0.0001, "HO": 0.0001,
    "GC": 0.10, "MGC": 0.10, "SI": 0.005, "HG": 0.0005,
    "ZC": 0.25, "ZS": 0.25, "ZW": 0.25,
    "6E": 0.00005, "6J": 0.0000005, "6B": 0.0001, "6C": 0.00005,
    "BTC": 5.00,
}


def tick_size_for(asset: str, default: float = 0.25) -> float:
    return TICK_SIZES.get((asset or "").upper(), default)
