"""Isolated, persistent PP-OCRv6-small inference; stdin/stdout JSON only."""
from pathlib import Path
import base64
import importlib.metadata
import json
import sys
import time

ROOT = Path(__file__).resolve().parent


def emit(data):
    print(json.dumps(data, ensure_ascii=False), flush=True)


def main():
    config = json.loads((ROOT / 'config/local_ocr_v6_small_v1.json').read_text(encoding='utf-8'))
    # Native wheels remain in their own Python 3.13 environment, never imported
    # into a different version or injected into the production UIA process.
    sys.path.insert(0, str(ROOT / config['environment'] / 'Lib/site-packages'))
    import cv2
    import numpy as np
    import onnxruntime as ort
    from rapidocr import RapidOCR, OCRVersion, ModelType
    from rapidocr.ch_ppocr_rec.typings import TextRecInput
    if importlib.metadata.version('rapidocr') != config['library'] or ort.__version__ != config['onnxruntime']:
        raise RuntimeError('OCR dependency identity changed')
    params = {
        'Global.log_level': 'warning', 'Global.text_score': config['text_score'],
        'EngineConfig.onnxruntime.intra_op_num_threads': config['threads'],
        'EngineConfig.onnxruntime.inter_op_num_threads': 1,
        'EngineConfig.onnxruntime.use_cuda': False,
        'EngineConfig.onnxruntime.use_dml': False,
    }
    for task, row in config['models'].items():
        params[task + '.model_path'] = str(ROOT / row['path'])
    for task in ('Det', 'Rec'):
        params[task + '.ocr_version'] = OCRVersion.PPOCRV6
        params[task + '.model_type'] = ModelType.SMALL
    started = time.perf_counter()
    engine = RapidOCR(params=params)
    emit(dict(ready=True, model=config['model'], pid=__import__('os').getpid(),
              load_ms=(time.perf_counter() - started) * 1000))

    def decode(encoded):
        image = cv2.imdecode(np.frombuffer(base64.b64decode(encoded, validate=True), dtype=np.uint8), cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError('Invalid OCR image')
        return image

    for line in sys.stdin:
        request = json.loads(line)
        if request['op'] == 'close':
            return 0
        try:
            started = time.perf_counter()
            if request['op'] == 'rec':
                result = engine._load_rec_model()(TextRecInput(img=[decode(v) for v in request['images']]))
                rows = [[str(t), float(s)] for t, s in zip(result.txts or [], result.scores)]
            elif request['op'] == 'scan':
                image = request.get('path') or decode(request['image'])
                result = engine(image, use_det=request['use_det'], use_cls=request['use_cls'])
                if getattr(result, 'boxes', None) is None and result.txts:
                    if isinstance(image, str):
                        from PIL import Image
                        with Image.open(image) as source:
                            w, h = source.size
                    else:
                        h, w = image.shape[:2]
                    rows = [[[[0, 0], [w, 0], [w, h], [0, h]], str(t), float(s)]
                            for t, s in zip(result.txts, result.scores)]
                elif getattr(result, 'boxes', None) is None:
                    rows = []
                else:
                    rows = [[b.tolist(), str(t), float(s)] for b, t, s in zip(result.boxes, result.txts, result.scores)]
            else:
                raise ValueError('Unknown OCR operation')
            emit(dict(id=request['id'], rows=rows, seconds=time.perf_counter() - started))
        except Exception as exc:
            emit(dict(id=request['id'], error=f'{type(exc).__name__}: {exc}'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
