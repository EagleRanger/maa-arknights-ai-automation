"""Synthetic-only beta checks; no game, MAA, ADB, network or private fixtures.

Run with Python from runtime/tools or pass --runtime PATH. Uses only stdlib.
"""
from __future__ import annotations
import argparse
import json
from datetime import datetime, timedelta
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--runtime',type=Path,default=Path(__file__).resolve().parents[1])
args,rest=parser.parse_known_args()
sys.path.insert(0,str(args.runtime.resolve()))
sys.dont_write_bytecode=True
import operator_training_v1 as training
import operator_training_infrast_v1 as infrast
import voucher_exchange_plan_v1 as voucher
import event_tl_task_rewards_v1 as rewards
import event_press_committee_v2 as committee
import press_committee_pages_v2 as pages

NOW=datetime.fromisoformat('2026-11-03T18:00:00+08:00')
GOAL=dict(name='Synthetic Operator',role='Warrior',skill=3,mastery=3)

def training_log(reason='PrerequisiteTraining',level=3):
    def cb(event,**row):
        return 'Assistant::append_callback | '+event+' '+json.dumps(dict(taskchain='OperProgress',uuid='synthetic-q',taskid=9,**row))+'\n'
    return ('append_task OperProgress {}\n'+cb('TaskChainStart')+
        cb('SubTaskExtraInfo',what='OperProgressDetail',details=dict(name=GOAL['name'],role='Warrior',result_detail=reason,skill_mastery=[0,0,level]))+
        cb('TaskChainCompleted')+'Assistant::append_callback | AllTasksCompleted {}\n')

def room_log():
    def cb(event,**row):
        return '[2026-11-03 17:59:00.000] Assistant::append_callback | '+event+' '+json.dumps(dict(taskchain='Infrast',uuid='synthetic-room',taskid=2,**row))+'\n'
    return cb('TaskChainStart')+cb('SubTaskExtraInfo',what='InfrastTrainingTimeLeft',details=dict(operator=GOAL['name'],skill='Synthetic Skill',level=2,time='01:20:00'))+cb('TaskChainCompleted')

class BetaChecks(unittest.TestCase):
    def test_training_order_does_not_enable_unrequested_upgrades(self):
        rows=training.goals(dict(schema_version=1,goals=[dict(GOAL,skill=s) for s in (3,2,1)]))
        plans=training.native_task(rows)['Plans']
        self.assertEqual([p['SkillMastery'] for p in plans],[[0,0,3],[0,3,0],[3,0,0]])
        self.assertTrue(all(p['Elite']==p['SkillLevel']==0 for p in plans))

    def test_training_started_and_busy_are_not_finished(self):
        for reason in ('Completed','PrerequisiteTraining','TrainingRoomBusy'):
            row=training.evaluate([GOAL],training_log(reason))
            self.assertEqual(row['status'],'waiting_training')
            self.assertIsNone(row['targets'][0]['observed_completed_level'])
        self.assertEqual(training.evaluate([GOAL],training_log('AlreadySatisfied'))['status'],'goals_complete')
        self.assertNotEqual(training.evaluate([GOAL],training_log('AlreadySatisfied',2))['status'],'goals_complete')

    def test_foreign_or_stopped_training_is_not_complete(self):
        good=training_log('AlreadySatisfied')
        foreign=good.replace('"taskid": 9','"taskid": 99',1)
        self.assertNotEqual(training.evaluate([GOAL],foreign)['status'],'goals_complete')
        self.assertEqual(training.evaluate([GOAL],good.replace('TaskChainCompleted','TaskChainStopped'))['status'],'queue_unverified')

    def test_invalid_targets_are_rejected(self):
        for row in (dict(GOAL,skill=0),dict(GOAL,mastery=True),dict(GOAL,module=1)):
            with self.assertRaises(ValueError):training.goals(dict(schema_version=1,goals=[row]))

    def test_current_infrast_busy_room_is_preserved(self):
        room=infrast.observation(room_log(),now=NOW)
        self.assertEqual(room['status'],'processing')
        self.assertEqual(room['details']['level'],2)
        app=SimpleNamespace(BASE='unused',_RUN_SUMMARY={infrast.KEY:room})
        with patch.object(infrast,'current_time',return_value=NOW),patch.object(infrast.fallback,'service',side_effect=AssertionError('no navigation')):
            row=infrast.service(app,packet=dict(schema_version=1,enabled=True,goals=[GOAL]))
        self.assertEqual(row['status'],'waiting_training')
        self.assertTrue(row['extra_operator_navigation_skipped'])

    def test_expired_room_returns_to_real_inspection(self):
        room=infrast.observation(room_log(),now=NOW)
        app=SimpleNamespace(BASE='unused',_RUN_SUMMARY={infrast.KEY:room})
        with patch.object(infrast,'current_time',return_value=NOW+timedelta(hours=2)),patch.object(infrast.fallback,'service',return_value={'status':'inspect'}) as fallback:
            self.assertEqual(infrast.service(app,packet=dict(schema_version=1,enabled=True,goals=[GOAL]))['status'],'inspect')
            fallback.assert_called_once()

    def test_voucher_monthly_refresh_and_full_remaining_cost(self):
        self.assertEqual(voucher.period(datetime.fromisoformat('2026-11-01T03:59:59+08:00'))[0],'2026-10')
        self.assertEqual(voucher.period(datetime.fromisoformat('2026-11-01T04:00:00+08:00'))[0],'2026-11')
        policy=dict(account='synthetic',yellow=dict(enabled=True))
        obs=dict(account='synthetic',cycle='2026-11',goods='standard_headhunting_bundle',observed_at=NOW.isoformat(),balance=257,purchased_tiers=[],evidence=['synthetic-frame'])
        row=voucher.yellow_plan(policy,obs,now=NOW)
        self.assertEqual((row['status'],row['remaining_cost'],row['resource_actions']),('save_for_complete_bundle',258,0))
        row=voucher.yellow_plan(policy,dict(obs,balance=230,purchased_tiers=[0,1]),now=NOW)
        self.assertEqual((row['status'],row['remaining_cost']),('complete_bundle_affordable',230))
        for change in (dict(account='foreign'),dict(balance=None),dict(purchased_tiers=[0,2]),dict(evidence=[]),dict(goods='kernel_headhunting_bundle')):
            self.assertTrue(voucher.yellow_plan(policy,dict(obs,**change),now=NOW)['status'].startswith('needs_'))

    def test_press_current_center_and_max_not_completion(self):
        row=dict(items=[('圣骏堡公报',800,710),('求真报',1700,100)],screenshot='synthetic')
        self.assertEqual(pages.paper(row),'圣骏堡公报')
        with patch.object(pages,'match',return_value=(1,1)),patch.object(pages,'reward_checks',return_value=[True,True,False,False]):
            self.assertEqual(pages.describe(object(),row)['status'],'max_reached_claims_need_review')
        with patch.object(pages,'match',return_value=(1,1)),patch.object(pages,'reward_checks',return_value=[True]*4):
            self.assertEqual(pages.describe(object(),row)['status'],'verified_complete')

    def test_press_extra_runs_between_progression_and_farm(self):
        order=[]
        app=SimpleNamespace(_RUN_SUMMARY={},mode_event_first_clear=lambda e:order.append('stages') or True,mode_event_rerun_tasks=Mock(),_maa_task_queue_running=lambda:False)
        def route(e):
            value=app.mode_event_first_clear(e);order.append('farm');return value
        app._run_full_event_steps=route
        with patch.object(committee,'service',side_effect=lambda a:order.append('extra') or {'status':'all_currently_unlocked_complete'}),committee.boundary(app):
            app._run_full_event_steps({'name':rewards.NAME})
        self.assertEqual(order,['stages','extra','farm'])

    def test_postfarm_reward_revisit_and_other_event_unchanged(self):
        calls=[]
        app=SimpleNamespace(claim_event_task_rewards=lambda e:False,mode_event=lambda:True,_plan_allows=lambda n:True,_maa_task_queue_running=lambda:False,_RUN_SUMMARY={})
        def route(e):app.claim_event_task_rewards(e);return app.mode_event()
        app._run_full_event_steps=route
        def claim(a,e):
            calls.append(e['name']);a._RUN_SUMMARY={'event':{'task_rewards':{'status':'verified_no_claimable','tl_visits':[1]}}};return True
        with patch.object(rewards,'applies',side_effect=lambda e:e.get('name')==rewards.NAME),patch.object(rewards,'claim',claim),rewards.boundary(app):
            self.assertTrue(app._run_full_event_steps({'name':rewards.NAME}))
            self.assertEqual(calls,[rewards.NAME,rewards.NAME])
            app._run_full_event_steps({'name':'other'})
            self.assertEqual(len(calls),2)

    def test_unrelated_claim_button_is_not_event_task_page(self):
        self.assertFalse(rewards.state([('键领取',1642,259),('完成待领取的任务',1170,257)])[0])

    def test_reward_submit_once_and_uncertain_receipt_never_repeats(self):
        pending=[(rewards.LABEL,800,50),('REQUIREMENT',500,400),('REWARDS',700,400),
                 ('完成待领取的任务',1170,257),('一键领取',1642,259)]
        frames=[pending]+[pending]*8+[pending]
        taps=[];sequence=iter(range(len(frames)))
        app=SimpleNamespace(shot=lambda tag:str(next(sequence)),ocr=lambda p:frames[int(p)],
            tap=lambda *xy:taps.append(xy),wait=lambda *a:None,_maa_task_queue_running=lambda:False,_RUN_SUMMARY={})
        self.assertFalse(rewards.claim(app,{}))
        self.assertFalse(rewards.claim(app,{}))
        self.assertEqual(taps,[(1642,259)])
        self.assertTrue(app._RUN_SUMMARY['event']['task_rewards']['tl_unreconciled'])

    def test_reward_result_and_same_page_empty_are_both_required(self):
        pending=[(rewards.LABEL,800,50),('REQUIREMENT',500,400),('REWARDS',700,400),
                 ('完成待领取的任务',1170,257),('一键领取',1642,259)]
        empty=[(rewards.LABEL,800,50),('REQUIREMENT',500,400),('REWARDS',700,400)]
        frames=[pending,[('获得物资',960,200)],empty]
        sequence=iter(range(len(frames)));taps=[]
        app=SimpleNamespace(shot=lambda tag:str(next(sequence)),ocr=lambda p:frames[int(p)],
            tap=lambda *xy:taps.append(xy),wait=lambda *a:None,_maa_task_queue_running=lambda:False,_RUN_SUMMARY={})
        self.assertTrue(rewards.claim(app,{}))
        self.assertEqual(app._RUN_SUMMARY['event']['task_rewards']['tl_verified_claims'],1)
        self.assertEqual(len(taps),2)

if __name__=='__main__':unittest.main(argv=[sys.argv[0]]+rest)
