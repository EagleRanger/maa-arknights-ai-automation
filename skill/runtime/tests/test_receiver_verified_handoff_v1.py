"""Public receiver tests; synthetic account and screens, no device or developer tree."""
from contextlib import ExitStack
from types import SimpleNamespace as N
from unittest.mock import Mock,patch
import json
import pytest
from PIL import Image
import funded_activity_v1 as farming
import event_map_reuse_v1 as maps
from operator_training_return_v1 import return_page
from receiver_setup_v1 import verified_event_scope


def occurrence():
    return dict(name='示例活动',stage_prefix='AB',start='2026-01-01T04:00:00',
                kind='rerun',replay_stages=['AB-7'],required_challenge_replays=['AB-7'],
                stages=[dict(display='AB-7',modes=['normal','challenge'])])


def test_public_complete_rerun_skips_the_map_and_can_still_collect_rewards(tmp_path):
    from receiver_operations_v1 import extra
    from ark_modules.core import Result
    event=occurrence()
    rows={k:dict(status='completed',actual_runs=1) for k in ('AB-7','AB-7:challenge')}
    app=N(_RUN_SUMMARY={},get_active_event=lambda:event,ACTIVE_EVENTS=[],_event_execution_stages=lambda e:e['stages'],
          _load_event_progress=lambda:{'events':{event['name']:{'task_replay':dict(event_start=event['start'],stages=rows)}}})
    collector=Mock(return_value=Result('succeeded','rewards',('reward-observation',),{}))
    session=N(app=app,output=tmp_path,events={},execute=collector,sequence=1)
    result=extra(session,{},None,{},'goal.event')
    assert result.status=='succeeded' and result.data['stages'][0]['new_battles']==0
    assert collector.call_args.args[0]=='activity.rewards'
    del rows['AB-7:challenge']
    assert maps.remaining_progress(app,event)==[('AB-7','challenge')]
    result=extra(session,{'include_challenge':False},None,{},'goal.event')
    assert result.status=='succeeded'


def test_package_reads_balance_on_exact_detail_and_rejects_neighbour(tmp_path):
    e=occurrence();frame=tmp_path/'detail.png';Image.new('RGB',(1920,1080)).save(frame)
    rows=[('OPERATIONAB-7',1396,145),('代理指挥+',1766,888),('开始行动',1766,986),('216/210',1800,58)]
    a=N(shot=lambda _:frame,ocr=lambda _:rows)
    assert farming.detail_balance(a,e,'AB-7')[0]==216
    assert farming.detail_balance(a,e,'AB-8') is None


def test_training_roster_needs_geometry_not_module_icons():
    header=[('等级',1308,50),('稀有度',1454,57),('悖论模拟',1603,57),('辅助',1857,60)]
    rows=header+[(t,x+dx,y+dy) for x in (388,628,868) for y in (492,970)
                        for t,dx,dy in [('40',0,0),('测试干员',100,52)]]
    assert return_page(rows)=='roster'
    assert return_page(rows+[('是否确认',900,560)]) is None


@pytest.mark.parametrize('single',[False,True])
def test_shared_receiver_scope_installs_then_restores_real_consumer(single):
    import arknights_daily_runtime_v12 as a
    import operator_training_v1 as training
    from ark_modules.domains import farming as domain
    before=(a._run_full_event_steps,a.verify_event_navigation_ready,a._open_event_stage_detail,domain.farm,training._service_one)
    with verified_event_scope(a,single=single):
        now=(a._run_full_event_steps,a.verify_event_navigation_ready,a._open_event_stage_detail,domain.farm,training._service_one)
        assert all(x is not y for x,y in zip(before[:4],now[:4]))
        if single:assert now[-1] is not before[-1]
    assert before==(a._run_full_event_steps,a.verify_event_navigation_ready,a._open_event_stage_detail,domain.farm,training._service_one)
