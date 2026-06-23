from typing import Any, List

import numpy as np
from scipy.stats import norm


def detect_outliers(values: List[float], timestamps: List[str], method: str) -> dict:
    if len(values) != len(timestamps):
        raise ValueError("values y timestamps deben tener la misma longitud")
    if len(values) == 0:
        raise ValueError("values no puede estar vacío")

    x = np.asarray(values, dtype=float)
    if not np.isfinite(x).all():
        raise ValueError("values no puede contener NaN/Inf")

    n = int(x.size)
    mean = float(x.mean())
    std = float(x.std(ddof=0))
    outliers: list[dict[str, Any]] = []

    if method == "3sigma":
        # Robust 3-sigma: median + MAD modified z-score (threshold 3.5).
        # Avoids masking, where a single large spike inflates mean/std and hides itself.
        median = float(np.median(x))
        mad = float(np.median(np.abs(x - median)))
        if mad != 0.0:
            scale = mad / 0.6745  # consistent estimator of std for normal data
        else:
            scale = std  # degenerate MAD; fall back to standard deviation
        upper = median + 3.5 * scale if scale != 0.0 else median
        lower = median - 3.5 * scale if scale != 0.0 else median
        for i, v in enumerate(x.tolist()):
            if v > upper:
                outliers.append({"index": i, "timestamp": timestamps[i], "value": float(v),
                                 "threshold_upper": upper, "threshold_lower": lower,
                                 "criterion": "exceeds_upper"})
            elif v < lower:
                outliers.append({"index": i, "timestamp": timestamps[i], "value": float(v),
                                 "threshold_upper": upper, "threshold_lower": lower,
                                 "criterion": "exceeds_lower"})

    elif method == "iqr":
        q1, q3 = np.percentile(x, [25, 75], method="linear")
        iqr = float(q3 - q1)
        lower = float(q1 - 1.5 * iqr)
        upper = float(q3 + 1.5 * iqr)
        for i, v in enumerate(x.tolist()):
            if v > upper:
                outliers.append({"index": i, "timestamp": timestamps[i], "value": float(v),
                                 "threshold_upper": upper, "threshold_lower": lower,
                                 "criterion": "exceeds_upper"})
            elif v < lower:
                outliers.append({"index": i, "timestamp": timestamps[i], "value": float(v),
                                 "threshold_upper": upper, "threshold_lower": lower,
                                 "criterion": "exceeds_lower"})

    elif method == "chauvenet":
        if std != 0.0:
            z = np.abs((x - mean) / std)
            probability = 1.0 - norm.cdf(z)
            mask = (n * probability) < 0.5
            for i in np.where(mask)[0].astype(int).tolist():
                outliers.append({"index": i, "timestamp": timestamps[i], "value": float(x[i]),
                                 "criterion": "chauvenet", "z_score": float(z[i]),
                                 "probability": float(probability[i])})
    else:
        raise ValueError(f"Método desconocido: {method}")

    return {
        "method": method,
        "outliers": outliers,
        "statistics": {"mean": mean, "std": std, "n": n, "outlier_count": len(outliers)},
    }
