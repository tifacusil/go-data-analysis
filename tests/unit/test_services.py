import pytest
from services import outliers_service, denoise_service, regression_service, predict_service

TIMESTAMPS = [f"2024-01-{i:02d}T00:00:00Z" for i in range(1, 9)]
VALUES = [1.0, 2.0, 2.5, 2.1, 1.9, 2.3, 100.0, 1.8]


class TestOutliers:
    def test_3sigma_detects_spike(self):
        result = outliers_service.detect_outliers(VALUES, TIMESTAMPS, "3sigma")
        assert result["method"] == "3sigma"
        indices = [o["index"] for o in result["outliers"]]
        assert 6 in indices  # 100.0 is the spike

    def test_iqr_detects_spike(self):
        result = outliers_service.detect_outliers(VALUES, TIMESTAMPS, "iqr")
        indices = [o["index"] for o in result["outliers"]]
        assert 6 in indices

    def test_chauvenet(self):
        result = outliers_service.detect_outliers(VALUES, TIMESTAMPS, "chauvenet")
        assert "outliers" in result

    def test_empty_values_raises(self):
        with pytest.raises(ValueError):
            outliers_service.detect_outliers([], [], "3sigma")

    def test_length_mismatch_raises(self):
        with pytest.raises(ValueError):
            outliers_service.detect_outliers([1.0, 2.0], ["t1"], "3sigma")


class TestDenoise:
    def test_wavelet(self):
        result = denoise_service.denoise(VALUES, TIMESTAMPS, "wavelet")
        assert len(result["denoised_values"]) == len(VALUES)
        assert result["method"] == "wavelet"

    def test_svm(self):
        result = denoise_service.denoise(VALUES, TIMESTAMPS, "svm")
        assert len(result["denoised_values"]) == len(VALUES)

    def test_invalid_method_raises(self):
        with pytest.raises(ValueError):
            denoise_service.denoise(VALUES, TIMESTAMPS, "unknown")


class TestRegression:
    def test_polynomial(self):
        result = regression_service.polynomial_regression(VALUES, TIMESTAMPS, degree=2)
        assert len(result["fitted_values"]) == len(VALUES)
        assert result["model"] == "polynomial"
        assert "r2_score" in result

    def test_bayesian(self):
        result = regression_service.bayesian_regression(VALUES, TIMESTAMPS)
        assert result["model"] == "bayesian"
        assert len(result["coefficients"]) == 2

    def test_bad_degree_raises(self):
        with pytest.raises(ValueError):
            regression_service.polynomial_regression(VALUES, TIMESTAMPS, degree=0)


class TestPredict:
    def test_arima(self):
        result = predict_service.arima_predict(VALUES, TIMESTAMPS, horizon=3, order=(1, 1, 1))
        assert len(result["predicted_values"]) == 3
        assert result["model"] == "arima"

    def test_gm11(self):
        result = predict_service.gm11_predict(VALUES[:4], TIMESTAMPS[:4], horizon=2)
        assert len(result["predicted_values"]) == 2
        assert result["model"] == "gm11"

    def test_gm11_needs_4_values(self):
        with pytest.raises(ValueError):
            predict_service.gm11_predict([1.0, 2.0], TIMESTAMPS[:2], horizon=1)
