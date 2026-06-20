import numpy as np
import pandas as pd
from sklearn.linear_model import BayesianRidge
from sklearn.metrics import r2_score


def _to_seconds(timestamps: list[str]) -> np.ndarray:
    dt = pd.to_datetime(timestamps, utc=True)
    return (dt - dt[0]).total_seconds().to_numpy(dtype=float)


def polynomial_regression(values: list[float], timestamps: list[str], degree: int = 3) -> dict:
    if degree < 1 or degree >= len(values):
        raise ValueError(f"degree must be >= 1 and < len(values) ({len(values)}), got {degree}")
    x = _to_seconds(timestamps)
    y = np.array(values, dtype=float)
    coeffs = np.polyfit(x, y, degree)
    fitted = np.polyval(coeffs, x)
    return {
        "coefficients": coeffs.tolist(),
        "fitted_values": fitted.tolist(),
        "r2_score": float(r2_score(y, fitted)),
        "model": "polynomial",
        "degree": degree,
    }


def bayesian_regression(values: list[float], timestamps: list[str]) -> dict:
    x = _to_seconds(timestamps).reshape(-1, 1)
    y = np.array(values, dtype=float)
    model = BayesianRidge()
    model.fit(x, y)
    fitted = model.predict(x)
    return {
        "coefficients": [float(model.intercept_), float(model.coef_[0])],
        "fitted_values": fitted.tolist(),
        "r2_score": float(r2_score(y, fitted)),
        "model": "bayesian",
        "degree": None,
    }
