"""Compatibility shim for RapidOCR builds without ``text_recognizer``.

The frozen daily runtime still needs the legacy recognizer shape for one small
proxy-multiplier crop.  Keep the accepted runtime immutable and adapt only the
OCR object created by it.
"""

from __future__ import annotations


def _legacy_text_recognizer(engine, images):
    rows = []
    elapsed = None
    for image in images:
        result, elapsed = engine(image)
        for row in result or []:
            if len(row) >= 3:
                rows.append((str(row[1]), float(row[2])))
            elif len(row) >= 2:
                rows.append((str(row[0]), float(row[1])))
    return rows, elapsed


def attach_text_recognizer(engine):
    if engine is None or hasattr(engine, "text_recognizer"):
        return engine

    def recognizer(images):
        return _legacy_text_recognizer(engine, images)

    engine.text_recognizer = recognizer
    return engine


def install_runtime_compat(app):
    """Attach after every lazy OCR initialization; idempotent and local."""
    attach_text_recognizer(getattr(app, "_ocr_engine", None))
    current = app.ocr
    if getattr(current, "_rapidocr_text_compat_v1", False):
        return current

    def compatible_ocr(path):
        items = current(path)
        attach_text_recognizer(getattr(app, "_ocr_engine", None))
        return items

    compatible_ocr._rapidocr_text_compat_v1 = True
    compatible_ocr._rapidocr_text_compat_original = current
    app.ocr = compatible_ocr
    return compatible_ocr
