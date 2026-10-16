"""Display unavailable research metrics without inventing zeros."""
import math


def metric_number(value, spec='.1f', *, scale=1.0, suffix='', sample_size=None):
    if sample_size == 0 or value is None or isinstance(value, bool):
        return '尚無有效樣本'
    try:
        number = float(value) * scale
        if not math.isfinite(number):
            return '資料不足'
        return format(number, spec) + suffix
    except (TypeError, ValueError):
        return '資料不足'
