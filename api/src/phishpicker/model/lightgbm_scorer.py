"""Runtime wrapper: load a LightGBM booster + its feature-column schema.

The booster is persisted via LightGBM's native `save_model` format (text file).
The feature-column list is persisted in a sibling `.meta.json`. At startup the
API asserts the persisted columns match FEATURE_COLUMNS — a mismatch means
training and serving disagree and must not be silently tolerated.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import lightgbm as lgb
import numpy as np


@dataclass
class LightGBMScorer:
    booster: lgb.Booster
    feature_columns: list[str]

    @classmethod
    def load(cls, path: Path) -> "LightGBMScorer":
        base = Path(path)
        booster = lgb.Booster(model_file=str(base))
        meta = json.loads(base.with_suffix(".meta.json").read_text())
        return cls(booster=booster, feature_columns=meta["feature_columns"])

    def assert_compatible_with(self, expected: tuple[str, ...] | list[str]) -> None:
        if tuple(self.feature_columns) != tuple(expected):
            raise ValueError(
                "Model schema mismatch between training and serving "
                f"(model has {len(self.feature_columns)} columns, "
                f"serving expects {len(expected)})"
            )

    def score(self, X: np.ndarray) -> np.ndarray:
        return self.booster.predict(X)


def save_model_artifact(path: Path, booster: lgb.Booster, columns: list[str]) -> None:
    base = Path(path)
    base.parent.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(base))
    base.with_suffix(".meta.json").write_text(json.dumps({"feature_columns": columns}))
