"""
facefocus.py
------------
Hero photos get cropped by CSS (object-fit: cover) into a fixed aspect
ratio on both the interview page and the homepage card. A single guessed
crop position (e.g. "always bias 15% from the top") works for *most* of
these concert/portrait shots, but not all of them -- it depends on how
far away the photo was taken from, and how much headroom/stage/crowd
surrounds the subject.

This does real face detection (OpenCV's bundled Haar cascade -- no network
access or extra model download needed) on each downloaded hero image, and
returns a CSS `object-position` vertical percentage that keeps the
*detected face* in frame, instead of a one-size-fits-all guess.
"""
from __future__ import annotations

from pathlib import Path

_face_cascade = None


def _get_cascade():
    global _face_cascade
    if _face_cascade is None:
        import cv2

        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        _face_cascade = cv2.CascadeClassifier(cascade_path)
    return _face_cascade


# Used whenever a face can't be detected (band photo shot from too far
# away, subject looking down/away, sunglasses, poor lighting, etc.) --
# same top-biased value used everywhere before per-photo detection existed.
FALLBACK_FOCUS_Y = "15%"


def detect_focus_y(image_path: Path) -> str:
    """Returns a CSS object-position vertical percentage (e.g. "18.4%")
    that keeps the main detected face in frame. Falls back to
    FALLBACK_FOCUS_Y if no face is found or detection fails for any
    reason (corrupt/unreadable image, missing OpenCV, etc.) -- this must
    never raise, since a bad photo shouldn't break the whole build."""
    try:
        import cv2

        img = cv2.imread(str(image_path))
        if img is None:
            return FALLBACK_FOCUS_Y
        height = img.shape[0]
        if height <= 0:
            return FALLBACK_FOCUS_Y

        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        faces = _get_cascade().detectMultiScale(
            gray, scaleFactor=1.1, minNeighbors=5, minSize=(40, 40)
        )
        if len(faces) == 0:
            return FALLBACK_FOCUS_Y

        # Multiple people can appear in a live shot (e.g. a drummer
        # further back) -- the largest detected face is the most reliable
        # signal for "the guitarist this photo is actually of", since
        # they're normally the closest subject to the camera.
        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
        face_center_y = (y + h / 2) / height

        # Clamp to a sane range: a face detected right at the very edge
        # is more likely a false positive than someone standing at the
        # extreme top/bottom of the frame, so don't let one throw the
        # crop to an extreme.
        face_center_y = max(0.05, min(face_center_y, 0.6))
        return f"{face_center_y * 100:.1f}%"
    except Exception:
        return FALLBACK_FOCUS_Y
