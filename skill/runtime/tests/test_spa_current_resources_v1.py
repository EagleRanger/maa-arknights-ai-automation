import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock, patch
import pytest
import maa_spa_resources_v1 as resources
import spa_core_trial_v1 as native


def source():
    rows={resources.PREFIX+n:{'action':'ClickSelf','next':[]} for n in resources.NEW}
    rows[resources.PREFIX+'Begin']={'algorithm':'JustReturn','next':[resources.PREFIX+resources.NEW[0]]}
    rows[resources.PREFIX+'ReturnHome']={'action':'ClickSelf','next':[resources.PREFIX+resources.NEW[0]]}
    rows[resources.PREFIX+'ReadyScreen']={'action':'ClickSelf','next':[resources.PREFIX+'Goliath']}
    rows[resources.PREFIX+'Goliath']={'action':'ClickSelf','next':[]}
    rows[resources.PREFIX+'StartSimulation2']['next']=[resources.PREFIX+'ReadyScreen','#self']
    return rows


def fake_fetch(path):
    if path.endswith('SPA.json'):return json.dumps(source()).encode()
    if path.endswith('version.json'):return b'{"activity":{"name":"SPA"}}'
    return b'\x89PNG\r\n\x1a\nfixture'


def prepared(tmp_path):
    installed=tmp_path/'install'; target=installed/'resource/tasks/MiniGame/SPA.json'
    target.parent.mkdir(parents=True);target.write_bytes(b'{}')
    out=tmp_path/'resources'
    return installed,out,resources.synchronize(installed,out,fake_fetch)


def test_upstream_preserved_and_one_round_overlay_separate(tmp_path):
    installed,out,r=prepared(tmp_path)
    original=json.loads((out/'upstream/SPA.json').read_text())
    overlay=json.loads((out/'overlay/resource/tasks/project_spa.json').read_text())
    assert original==source()
    assert overlay[resources.PREFIX+'ReturnHome']['next']==[]
    assert overlay[resources.PREFIX+'StartSimulation2']['next']==[
        resources.PREFIX+'Goliath',resources.PREFIX+'ReadyScreen','#self']
    assert original[resources.PREFIX+'StartSimulation2']['next']==[resources.PREFIX+'ReadyScreen','#self']
    assert (installed/'resource/tasks/MiniGame/SPA.json').read_bytes()==b'{}'
    assert resources.verify(out)==r
    assert resources.synchronize(installed,out,Mock(side_effect=AssertionError('no hot reload')))==r


def test_resource_drift_rejected_before_core(tmp_path):
    _,out,_=prepared(tmp_path)
    (out/'overlay/resource/tasks/project_spa.json').write_text('{}')
    with pytest.raises(ValueError,match='changed'):resources.verify(out)


@pytest.mark.parametrize('change',['foreign','missing','terminal'])
def test_new_incompatible_upstream_does_not_get_silent_legacy_fallback(change):
    x=source()
    if change=='foreign':x['FightBegin']={}
    elif change=='missing':del x[resources.PREFIX+resources.NEW[0]]
    else:x[resources.PREFIX+'ReturnHome']['action']='ClickRect'
    with pytest.raises(ValueError):resources.single_round(x)


def test_invalid_template_rejected(tmp_path):
    root=tmp_path/'install'; p=root/'resource/tasks/MiniGame/SPA.json';p.parent.mkdir(parents=True);p.write_text('{}')
    def fetch(path):return b'not png' if path.endswith('.png') else fake_fetch(path)
    with pytest.raises(ValueError,match='PNG'):resources.synchronize(root,tmp_path/'out',fetch)
    assert not (tmp_path/'out/sync.json').exists()


class Call:
    def __init__(self, fn):self.fn=fn
    def __call__(self,*args):return self.fn(*args)


@pytest.mark.parametrize('entry',native.ENTRIES)
@pytest.mark.parametrize('failure',[False,True])
@pytest.mark.parametrize('lobby',['ReturnHome','MiniGame@SPA@ReturnHome'])
def test_native_result_never_claims_reward_and_preserves_environment(tmp_path,failure,entry,lobby):
    installed,out,_=prepared(tmp_path); callbacks=[]; calls=[]
    def create(cb,_):callbacks.append(cb);return 17
    def start(handle):
        cb=callbacks[0]
        cb(20002,json.dumps({'details':{'task':lobby}}).encode(),None)
        cb(10000 if failure else 10002,b'{"taskchain":"Custom"}',None)
        return 1
    core=SimpleNamespace(**{name:Call(fn) for name,fn in {
        'AsstSetUserDir':lambda *a:1,'AsstLoadResource':lambda *a:1,'AsstCreateEx':create,
        'AsstDestroy':lambda *a:None,'AsstSetConnectionExtras':lambda *a:None,'AsstConnect':lambda *a:1,
        'AsstAppendTask':lambda h,t,p:calls.append(json.loads(p)) or 1,'AsstStart':start,
        'AsstStop':lambda *a:1,'AsstRunning':lambda *a:0}.items()})
    app=SimpleNamespace(_maa_task_queue_running=lambda:False,_close_maacore_screenshot_bridge=Mock(),
        _stop_idle_maa_for_update=Mock(),_maa_install_root=lambda:str(installed),
        _maa_mumu_core_extras=lambda:'{}',ADB='adb.exe',DEVICE='test')
    with patch.object(native.ctypes,'WinDLL',return_value=core),patch.object(native.os,'add_dll_directory',return_value=MagicMock()):
        result=native.run(app,tmp_path/'core',out,10**12,entry_task=entry)
    assert result['status']==('needs_ai' if failure else 'native_cycle_returned')
    assert not result['game_reward_verified'] and not result['environment_cleanup']
    assert calls==[{'task_names':['MiniGame@SPA@'+entry]}]
    assert app._spa_core_owned is False
    with pytest.raises(FileExistsError):native.run(app,tmp_path/'core',out,10**12)


def test_unknown_native_entry_cannot_start_controller(tmp_path):
    with pytest.raises(ValueError,match='resume entry'):
        native.run(None,tmp_path/'core',tmp_path/'resources',10**12,entry_task='FightBegin')
    assert not (tmp_path/'core').exists()
