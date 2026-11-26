"""Public receiver contract, synthetic game UI and native transport; no account or network."""
import json
from types import SimpleNamespace
from unittest.mock import Mock,patch
import pytest
import receiver_goals_v1 as goals
from receiver_catalog_v1 import validate
from receiver_operations_v1 import Session,binding
from paradox_simulation_v1 import one_module


def test_player_goal_and_default_are_distinct():
    assert goals.compile_goal('paradox',{})==('operator.paradox',{})
    assert goals.compile_goal('daily',{})==('daily.full',{})
    assert goals.goal_steps('operator.paradox',{})==[dict(key='requested',task='operator.paradox',inputs={})]
    assert binding('operator.paradox')[1] is one_module
    assert goals.describe('paradox')[0]['command']=='python ark.py run paradox'
    with pytest.raises(ValueError):validate('operator.paradox',{'operator':'作者的干员'})


def test_receiver_calls_specialised_task_then_reads_game_result(tmp_path):
    resource=tmp_path/'resource';tiles=resource/'Arknights-Tile-Pos';tiles.mkdir(parents=True)
    stage='mem_mock_1'; title='演练甲'; name='测试甲'
    (resource/'battle_data.json').write_text(json.dumps({'chars':{'char_123_mock':{'name':name}}}))
    row=dict(code=stage,stageId=stage,name=title,filename='map.json')
    (tiles/'overview.json').write_text(json.dumps({'a':row}));(tiles/'map.json').write_text(json.dumps(row))
    job=dict(stage_name=stage,opers=[dict(name=name,skill=3)],actions=[dict(type='Deploy')])
    item=dict(id=42,available=True,content=json.dumps(job))
    fields=[('悖论模拟',1736,130),(title,1825,221),('开始模拟',1766,987)]
    skills=[('一技能',485,355),('二技能',485,665),('三技能',485,976)]
    frames={'paradox_roster':[('等级',1307,51),('悖论模拟',1603,57),('未通过',134,545)],
            'paradox_operator':fields,'paradox_before_native_start':fields,'paradox_choose_job_skill':skills,
            'paradox_skill_ready':skills+[('开始模拟',1537,924)],
            'paradox_settlement':fields+[('已完成模拟作战',177,1012)]}
    app=SimpleNamespace(_RUN_MUTEX_HANDLE=1,_maa_install_root=lambda:tmp_path,_maa_task_queue_running=lambda:False,
        ocr=frames.__getitem__,shot=lambda tag:tag,tap=Mock(),wait=Mock(),_RUN_SUMMARY={},
        _fetch_prts_json=lambda url:{'status_code':200,'data':{'data':[item]} if '/query?' in url else item})
    session=Session(app,tmp_path/'out',owns_control=lambda _:True)
    ctx=SimpleNamespace(owner='test',run_id='test',workflow='single')
    with patch('maa_utility_custom_v1._submit',return_value={'status':'native_completed_effect_pending','callbacks':'mock.json'}) as native:
        assert session.execute('operator.paradox',{},ctx).status=='succeeded'
        assert native.call_args.args[1]=='ParadoxCopilot'
        assert app.tap.call_count==3
        frames['paradox_settlement']=fields  # Same title but no clearance marker.
        assert session.execute('operator.paradox',{},ctx).status=='partial'
