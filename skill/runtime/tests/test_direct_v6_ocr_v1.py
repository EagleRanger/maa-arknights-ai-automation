import builtins
from types import SimpleNamespace
from unittest.mock import Mock
import cv2
import numpy as np
import pytest
import local_ocr_v6_small_v2 as provider


@pytest.fixture
def direct(monkeypatch):
    workers=[]
    class Worker:
        def __init__(self,*args,**kwargs):
            self.closed=0;self.calls=[];self.text='邀请';workers.append(self)
        def request(self,kind,**kwargs):
            self.calls.append((kind,kwargs))
            rows=[[[[1,2],[5,2],[5,6],[1,6]],self.text,.99]] if kind=='scan' else [['START',.99]]
            return dict(rows=rows,seconds=.01)
        def close(self):self.closed+=1
    monkeypatch.setattr(provider,'Worker',Worker)
    original=builtins.__import__
    def no_legacy(name,*args,**kwargs):
        if name.startswith('rapidocr_onnxruntime'):raise AssertionError('old OCR package requested')
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,'__import__',no_legacy)
    return workers


def test_one_shared_worker_for_nested_and_standalone_readers(direct):
    with provider.reader() as first:
        with provider.reader() as second:
            assert first.worker is second.worker and first is provider.current_engine()
            second.use_text_det=False
            assert first.use_text_det is True
        assert direct[0].closed==0
    assert len(direct)==1 and direct[0].closed==1
    with pytest.raises(RuntimeError,match='no legacy'):provider.current_engine()


def test_actual_cold_ocr_and_dependency_checks_need_no_old_package(direct):
    import arknights_daily_runtime_v12 as app
    old=app._ocr_engine
    with provider.boundary(app):
        app._ocr_engine=None
        assert app.ocr('fixture.png')==[('邀请',3,4)]
        assert app._runtime_dependencies_ready() is True
    assert app._ocr_engine is old and len(direct)==1 and direct[0].closed==1


def test_startup_symbol_probe_does_not_import_old_ocr(direct):
    import run_daily_v19
    assert run_daily_v19._runtime_probe()['symbols_ready'] is True
    assert direct==[]


def test_actual_activity_helpers_share_v6_and_keep_roi_decisions(tmp_path,direct):
    import activity_room_invite_prepare_v1 as invite
    import activity_room_trust_select_v1 as trust
    path=tmp_path/'static.png'
    ok,encoded=cv2.imencode('.png',np.zeros((1080,1920,3),dtype=np.uint8))
    assert ok
    path.write_bytes(encoded.tobytes())
    with provider.reader():
        assert invite.isolated_invite(path) is True
        direct[0].text='50%'
        rows=trust.card_trust_ocr(path)
        assert len(rows)==12 and all(t=='50%' for t,x,y in rows)
    assert len(direct)==1 and direct[0].closed==1


def test_final_composition_retains_captured_ocr_and_closes_on_error(direct,monkeypatch):
    import arknights_daily_runtime_v12 as app
    import run_daily as base
    captured=app.ocr
    def task():
        app._ocr_engine=None
        assert captured('fixture.png')==[('邀请',3,4)]
        raise ValueError('test original failure')
    monkeypatch.setattr(base,'main',task)
    with pytest.raises(ValueError,match='original failure'):
        provider.run_composed(lambda:base.main(),app)
    assert len(direct)==1 and direct[0].closed==1


def test_old_import_path_has_no_second_implementation(direct):
    import local_ocr_v6_small_v1 as prior
    assert prior.reader is provider.reader and prior.boundary is provider.boundary
