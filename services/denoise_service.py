from __future__ import annotations

from typing import Any, List

import numpy as np


def _moving_average(values: np.ndarray, window: int) -> np.ndarray:
    n = int(values.size)
    w = max(1, min(int(window), n))
    return np.convolve(values, np.ones(w) / w, mode="same").astype(float)


def _denoise_wavelet(values: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    try:
        import pywt
    except ModuleNotFoundError:
        denoised = _moving_average(values, 5)
        return denoised, {"fallback": "moving_average", "window": min(5, int(values.size))}

    n = int(values.size)
    if n < 4:
        return values.copy(), {"wavelet": None, "level": 0, "threshold": 0.0, "mode": "soft", "sigma": 0.0}

    wavelet_name, mode = "db4", "soft"
    max_level = int(pywt.dwt_max_level(n, pywt.Wavelet(wavelet_name).dec_len))
    level = min(4, max_level) if max_level > 0 else 0
    if level == 0:
        return values.copy(), {"wavelet": wavelet_name, "level": 0, "threshold": 0.0, "mode": mode, "sigma": 0.0}

    coeffs = pywt.wavedec(values, wavelet_name, level=level)
    finest = coeffs[-1]
    sigma = float(np.median(np.abs(finest)) / 0.6745) if finest.size > 0 else 0.0
    threshold = float(sigma * np.sqrt(2.0 * np.log(n))) if sigma > 0.0 else 0.0
    new_coeffs = [coeffs[0]] + [pywt.threshold(c, threshold, mode=mode) for c in coeffs[1:]]
    denoised = pywt.waverec(new_coeffs, wavelet_name)[:n].astype(float)
    return denoised, {"wavelet": wavelet_name, "level": level, "threshold": threshold, "mode": mode, "sigma": sigma}


def _zero_crossing_rate(x: np.ndarray) -> float:
    n = int(x.size)
    return float(np.sum(x[:-1] * x[1:] < 0.0) / (n - 1)) if n >= 2 else 0.0


def _denoise_emd(values: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    try:
        from PyEMD import EMD
    except ModuleNotFoundError:
        denoised = _moving_average(values, 7)
        return denoised, {"fallback": "moving_average", "window": min(7, int(values.size))}

    n = int(values.size)
    if n < 4:
        return values.copy(), {"imf_count": 0, "removed_imfs": [], "strategy": "zcr_quantile", "quantile": 0.8}

    imfs = EMD().emd(values)
    if imfs is None or imfs.size == 0:
        return values.copy(), {"imf_count": 0, "removed_imfs": [], "strategy": "zcr_quantile", "quantile": 0.8}

    imf_count = int(imfs.shape[0])
    zcrs = np.array([_zero_crossing_rate(imfs[i]) for i in range(imf_count)])
    quantile = 0.8
    cutoff = float(np.quantile(zcrs, quantile)) if imf_count > 1 else float(zcrs[0])
    removed = np.where(zcrs >= cutoff)[0].astype(int).tolist()
    if imf_count > 1 and not removed:
        removed = [int(np.argmax(zcrs))]
    if len(removed) >= imf_count:
        removed = removed[:-1]

    keep_mask = np.ones(imf_count, dtype=bool)
    keep_mask[removed] = False
    residue = values - imfs.sum(axis=0)
    kept = imfs[keep_mask].sum(axis=0) if keep_mask.any() else np.zeros(n)
    return (residue + kept).astype(float), {
        "imf_count": imf_count, "removed_imfs": removed,
        "strategy": "zcr_quantile", "quantile": quantile, "zcrs": zcrs.tolist(),
    }


def _denoise_svm(values: np.ndarray) -> tuple[np.ndarray, dict[str, Any]]:
    try:
        from sklearn.pipeline import Pipeline
        from sklearn.preprocessing import StandardScaler
        from sklearn.svm import SVR
    except ModuleNotFoundError:
        denoised = _moving_average(values, 5)
        return denoised, {"fallback": "moving_average", "window": min(5, int(values.size))}

    n = int(values.size)
    if n < 2:
        return values.copy(), {"kernel": "rbf", "C": None, "epsilon": None, "gamma": "scale"}

    x = np.arange(n, dtype=float).reshape(-1, 1)
    y_std = float(np.std(values))
    epsilon = float(0.1 * y_std) if y_std > 0.0 else 0.1
    model = Pipeline([("scaler", StandardScaler()), ("svr", SVR(kernel="rbf", C=10.0, epsilon=epsilon, gamma="scale"))])
    model.fit(x, values.astype(float))
    return model.predict(x).astype(float), {"kernel": "rbf", "C": 10.0, "epsilon": epsilon, "gamma": "scale"}


def denoise(values: List[float], timestamps: List[str], method: str) -> dict:
    if len(values) == 0:
        raise ValueError('"values" no puede estar vacío.')
    if len(values) != len(timestamps):
        raise ValueError('La longitud de "timestamps" debe coincidir con la de "values".')

    arr = np.asarray(values, dtype=float)
    if not np.isfinite(arr).all():
        raise ValueError('"values" no puede contener NaN/Inf.')

    normalized = method.strip().lower()
    if normalized == "wavelet":
        denoised, params = _denoise_wavelet(arr)
    elif normalized == "emd":
        denoised, params = _denoise_emd(arr)
    elif normalized == "svm":
        denoised, params = _denoise_svm(arr)
    else:
        raise ValueError(f'Método inválido: "{method}". Use "wavelet", "emd" o "svm".')

    return {"denoised_values": denoised.tolist(), "method": normalized, "params": params}
