def test_lightgbm_imports():
    import lightgbm as lgb

    assert hasattr(lgb, "LGBMRanker")


def test_numpy_imports():
    import numpy as np

    assert np.__version__


def test_phishpicker_train_package_exists():
    import phishpicker.train  # noqa: F401
