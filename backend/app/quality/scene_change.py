"""Lightweight visual-change scores between consecutive images.

A high score is a possible visual discontinuity. Camera motion, lighting,
and moving players can raise it too. This is not a biomechanical event and
it does not change pose landmarks.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import cv2
import numpy as np


class SceneChangeError(ValueError):
    """Two frames cannot be compared."""


@dataclass(frozen=True)
class VisualChange:
    """Mean absolute grayscale difference, divided by 255, between two images."""

    from_index: int
    to_index: int
    mean_absolute_difference_ratio: float
    flagged_exploratory: bool = False


def mean_absolute_difference_ratio(previous: np.ndarray, current: np.ndarray) -> float:
    """Return a score in 0..1 for two uint8 images. Identical images score 0."""
    _require_image(previous)
    _require_image(current)
    if previous.shape != current.shape or previous.size == 0:
        raise SceneChangeError(
            f"Frames must share a non-empty shape, got {previous.shape} and {current.shape}."
        )
    before = np.ascontiguousarray(_gray(previous))
    after = np.ascontiguousarray(_gray(current))
    difference = cv2.absdiff(before, after).astype(np.float64)
    return float(difference.mean() / 255.0)


def visual_changes(
    frames: Sequence[np.ndarray],
    exploratory_limit: float | None = None,
) -> tuple[VisualChange, ...]:
    """Score every consecutive pair.

    ``from_index`` and ``to_index`` are positions in this sequence, not video
    frame numbers. ``exploratory_limit`` is optional. ``None`` means nothing is
    flagged. A flagged pair is only a possible visual discontinuity, not a
    confirmed cut. The limit must be a finite number >= 0. A boolean is rejected.
    """
    _require_limit(exploratory_limit)
    changes: list[VisualChange] = []
    for index, (previous, current) in enumerate(zip(frames, frames[1:])):
        score = mean_absolute_difference_ratio(previous, current)
        changes.append(
            VisualChange(
                from_index=index,
                to_index=index + 1,
                mean_absolute_difference_ratio=score,
                flagged_exploratory=exploratory_limit is not None and score >= exploratory_limit,
            )
        )
    return tuple(changes)


def _require_image(image: np.ndarray) -> None:
    if not isinstance(image, np.ndarray):
        raise SceneChangeError(f"Expected a NumPy array, got {type(image).__name__}.")
    if image.dtype != np.uint8:
        raise SceneChangeError(f"Expected uint8 pixels, got {image.dtype}.")
    if not np.isfinite(image.astype(np.float64)).all():
        raise SceneChangeError("Image values must be finite.")


def _require_limit(value: float | None) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SceneChangeError(f"Exploratory limit must be a number >= 0 or None, got {value!r}.")
    if value != value or value in (float("inf"), float("-inf")) or value < 0:
        raise SceneChangeError(f"Exploratory limit must be finite and >= 0, got {value!r}.")


def _gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image
    if image.ndim == 3 and image.shape[2] == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    raise SceneChangeError(f"Expected a gray or BGR image, got shape {image.shape}.")
