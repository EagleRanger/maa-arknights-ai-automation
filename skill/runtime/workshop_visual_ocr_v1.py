"""Supplement isolated workshop glyphs missed by full-frame detection."""
from pathlib import Path
import hashlib
import re


REFERENCE = Path(__file__).resolve().parent/'assets/activity_room_visual_v1/workshop_zero_lmd_reference.png'
REFERENCE_SHA256 = 'db8dfd327a445c5e31a508c7b4f30b67d282c9b6c36973daf455171d544b9187'
EIGHT_REFERENCE = Path(__file__).resolve().parent/'assets/activity_room_visual_v1/workshop_mood8_reference.png'
EIGHT_SHA256 = 'b1173118b5f6c09188b0eb0ab7db76123d65977b7b91e96ea4b512c073a12d8a'


def items(runtime, path):
    values = list(runtime.ocr(path))
    import cv2
    import numpy as np
    frame = cv2.imdecode(np.frombuffer(Path(path).read_bytes(), np.uint8), cv2.IMREAD_COLOR)
    if frame is None or frame.shape[:2] != (1080, 1920):
        return values
    engine = getattr(runtime, '_ocr_engine', None)
    if engine is not None:
        for box, centre in (((880, 290, 950, 335), (915, 313)), ((1600, 500, 1730, 610), (1660, 560))):
            x0, y0, x1, y1 = box
            present = any(x0 <= x <= x1 and y0 <= y <= y1 for _, x, y in values)
            if present:
                continue
            found, _ = engine.text_recognizer([frame[y0:y1, x0:x1]])
            if centre == (1660, 560) and not any(float(score) >= .45 and re.fullmatch(r'\d+', str(t)) for t, score in found or []):
                roi = cv2.copyMakeBorder(frame[y0:y1, x0:x1], 10, 10, 10, 10,
                                        cv2.BORDER_CONSTANT, value=(70, 70, 70))
                found, _ = engine.text_recognizer([roi])
            for text, confidence in found or []:
                if float(confidence) >= .45 and (text == '碳' or re.fullmatch(r'\d+', str(text))):
                    values.append((str(text), *centre))
        if not any(1700 < x < 1850 and 305 < y < 370 and re.fullmatch(r'\d+', t) for t, x, y in values):
            roi = cv2.copyMakeBorder(frame[310:370, 1725:1810], 20, 20, 20, 20,
                                    cv2.BORDER_CONSTANT, value=(70, 70, 70))
            found, _ = engine.text_recognizer([roi])
            for text, confidence in found or []:
                if float(confidence) >= .45 and re.fullmatch(r'\d+', str(text)):
                    values.append((str(text), 1760, 340))
    if not any(1700 < x < 1850 and 305 < y < 370 and re.fullmatch(r'\d+', t) for t, x, y in values):
        if EIGHT_REFERENCE.is_file() and hashlib.sha256(EIGHT_REFERENCE.read_bytes()).hexdigest() == EIGHT_SHA256:
            ref = cv2.imdecode(np.frombuffer(EIGHT_REFERENCE.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
            def eight_mask(image):
                roi = cv2.cvtColor(image[315:370, 1725:1810], cv2.COLOR_BGR2HSV)
                return cv2.inRange(roi, (0, 0, 210), (179, 65, 255)) > 0
            a, b = eight_mask(frame), eight_mask(ref)
            union = int((a | b).sum())
            if union >= 40 and int((a & b).sum())/union >= .97:
                values.append(('8', 1760, 340))
    if not any(1490 < x < 1620 and 305 < y < 370 and re.fullmatch(r'\d+', t) for t, x, y in values):
        # Only accept the exactly observed blue zero glyph, never infer free
        # processing from absent OCR. Other fees must be read as actual digits.
        if REFERENCE.is_file() and hashlib.sha256(REFERENCE.read_bytes()).hexdigest() == REFERENCE_SHA256:
            ref = cv2.imdecode(np.frombuffer(REFERENCE.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
            def zero_mask(image):
                roi = cv2.cvtColor(image[315:370, 1525:1595], cv2.COLOR_BGR2HSV)
                return cv2.inRange(roi, (85, 100, 170), (120, 255, 255)) > 0
            a, b = zero_mask(frame), zero_mask(ref)
            union = int((a | b).sum())
            if union >= 40 and int((a & b).sum())/union >= .97:
                values.append(('0', 1560, 340))
    return values
