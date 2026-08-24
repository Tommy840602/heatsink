import numpy as np

from app.engineering.surrogate.models import ResponseSurfaceModel


def test_uniform_surrogate_lifecycle_fit_predict_evaluate_save_load(tmp_path):
    x = np.asarray([[value, value**2] for value in np.linspace(0, 1, 20)])
    y = 2.0 + 3.0 * x[:, 0] - 0.5 * x[:, 1]
    model = ResponseSurfaceModel().fit(x, y)
    metrics = model.evaluate(x, y)
    assert metrics["r2"] > 0.999
    artifact = tmp_path / "rsm.joblib"
    model.save(artifact)
    restored = ResponseSurfaceModel.load(artifact)
    assert np.allclose(model.predict(x), restored.predict(x))
