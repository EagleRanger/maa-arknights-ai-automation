"""V6-small local OCR with the accepted legacy full-frame/ROI interface.

One owned inference worker per business scope. No screenshots, GUI, game,
network, fallback guessing, or changes to the production Python environment.
"""
from contextlib import contextmanager
from pathlib import Path
from queue import Queue, Empty
from threading import Thread, RLock
from unittest.mock import patch
import atexit
import base64
import hashlib
import importlib.metadata
import json
import os
import subprocess

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / 'config/local_ocr_v6_small_v1.json'


def preflight(root=ROOT):
    root = Path(root).resolve()
    data = json.loads((root / CONFIG.relative_to(ROOT)).read_text(encoding='utf-8'))
    if data['model'] != 'PP-OCRv6-small' or data['threads'] != 2:
        raise ValueError('OCR model/config identity changed')
    for row in data['models'].values():
        path = (root / row['path']).resolve()
        path.relative_to(root)
        if hashlib.sha256(path.read_bytes()).hexdigest().upper() != row['sha256']:
            raise ValueError('OCR model fingerprint changed: ' + row['path'])
    if not Path(data['base_python']).is_file():
        raise FileNotFoundError('OCR Python missing')
    if not (root / data['environment'] / 'Lib/site-packages/rapidocr/__init__.py').is_file():
        raise FileNotFoundError('Isolated OCR environment missing')
    versions = {d.metadata['Name'].lower().replace('_', '-'): d.version
                for d in importlib.metadata.distributions(path=[str(root / data['environment'] / 'Lib/site-packages')])}
    if versions.get('rapidocr') != data['library'] or versions.get('onnxruntime') != data['onnxruntime']:
        raise ValueError('Isolated OCR dependency identity changed')
    return data


def encode_image(image):
    import cv2
    ok, encoded = cv2.imencode('.png', image)
    if not ok:
        raise ValueError('OCR image could not be encoded')
    return base64.b64encode(encoded.tobytes()).decode('ascii')


class Worker:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.config = preflight(root)
        self.process = None
        self.stderr = None
        self.responses = Queue(maxsize=2)
        self.lock = RLock()
        self.sequence = 0
        self.ready = None
        atexit.register(self.close)

    def _read(self):
        try:
            for line in self.process.stdout:
                self.responses.put(json.loads(line))
        except Exception as exc:
            self.responses.put({'error': str(exc)})
        finally:
            self.responses.put({'error': 'OCR worker ended'})

    def _receive(self, timeout):
        try:
            row = self.responses.get(timeout=timeout)
        except Empty:
            self.close()
            raise TimeoutError('Local OCR timed out; no game action was repeated') from None
        if row.get('error'):
            self.close()
            raise RuntimeError(row['error'])
        return row

    def start(self):
        with self.lock:
            if self.process is not None:
                if self.process.poll() is not None:
                    raise RuntimeError('OCR worker exited; no blind restart')
                return
            logs = self.root / 'outputs/local_ocr'
            logs.mkdir(exist_ok=True)
            self.stderr = (logs / f'worker-{os.getpid()}.stderr.log').open('a', encoding='utf-8')
            env = dict(os.environ)
            env.pop('PYTHONPATH', None)
            env.pop('PYTHONHOME', None)
            env['PYTHONUTF8'] = '1'
            env['OMP_NUM_THREADS'] = str(self.config['threads'])
            env['OPENBLAS_NUM_THREADS'] = str(self.config['threads'])
            try:
                # Use the real interpreter, not Windows venv's launcher child:
                # process ownership/termination must address the actual worker.
                self.process = subprocess.Popen(
                    [self.config['base_python'], '-X', 'utf8', '-u', str(self.root / 'local_ocr_worker_v1.py')],
                    cwd=self.root, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                    stderr=self.stderr, text=True, encoding='utf-8',
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                )
                Thread(target=self._read, daemon=True).start()
                self.ready = self._receive(self.config['startup_timeout'])
                if self.ready.get('model') != self.config['model'] or self.ready.get('pid') != self.process.pid:
                    raise RuntimeError('OCR worker identity mismatch')
            except Exception:
                self.close()
                raise

    def request(self, op, **values):
        with self.lock:
            self.start()
            self.sequence += 1
            payload = dict(id=self.sequence, op=op, **values)
            try:
                self.process.stdin.write(json.dumps(payload, ensure_ascii=False) + '\n')
                self.process.stdin.flush()
                result = self._receive(self.config['request_timeout'])
                if result.get('id') != self.sequence:
                    raise RuntimeError('OCR response belongs to another request')
                return result
            except Exception:
                self.close()
                raise

    def close(self):
        with self.lock:
            process = self.process
            if process is not None:
                if process.poll() is None:
                    try:
                        process.stdin.write('{"op":"close"}\n')
                        process.stdin.flush()
                        process.wait(timeout=2)
                    except (OSError, subprocess.TimeoutExpired):
                        process.terminate()
                        try:
                            process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=2)
                for stream in (process.stdin, process.stdout):
                    if stream:
                        stream.close()
            if self.stderr:
                self.stderr.close()


class LegacyEngine:
    def __init__(self, worker):
        self.worker = worker
        self.use_text_det = True
        self.use_angle_cls = True

    def __call__(self, image, **kwargs):
        values = dict(use_det=kwargs.get('use_det', self.use_text_det),
                      use_cls=kwargs.get('use_cls', self.use_angle_cls))
        if isinstance(image, (str, Path)):
            values['path'] = str(Path(image).resolve())
        else:
            values['image'] = encode_image(image)
        result = self.worker.request('scan', **values)
        return result['rows'], result['seconds']

    def text_recognizer(self, images):
        # A single ndarray is one image, never a list of its pixel rows.
        if hasattr(images, 'shape'):
            images = [images]
        result = self.worker.request('rec', images=[encode_image(image) for image in images])
        return [(str(t), float(s)) for t, s in result['rows']], result['seconds']


@contextmanager
def reader():
    """Shared opt-in entry for independent modules; no implicit daily/cleanup."""
    worker = Worker()
    try:
        yield LegacyEngine(worker)
    finally:
        worker.close()


@contextmanager
def boundary(app):
    import rapidocr_onnxruntime as legacy
    worker = Worker()
    old_engine = app._ocr_engine
    def factory(*args, **kwargs):
        if args or kwargs:
            raise ValueError('Unsupported legacy OCR constructor options')
        return LegacyEngine(worker)
    try:
        # Existing OCR wrappers and all their captured functions are retained.
        # Both lazy main OCR and direct local helpers use the same owned worker.
        app._ocr_engine = factory()
        with patch.object(legacy, 'RapidOCR', factory):
            yield worker
    finally:
        app._ocr_engine = old_engine
        worker.close()


def run_composed(operation, app):
    import run_daily as base
    original = base.main
    def main(*args, **kwargs):
        with boundary(app):
            app.log('[本地OCR] PP-OCRv6 small 已挂载，整图与数字裁切共用隔离模型')
            return original(*args, **kwargs)
    with patch.object(base, 'main', main):
        return operation()
