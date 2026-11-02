"""Reviewed weekly repair using the complete V115 host and one scoped call."""
import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import sys
from unittest.mock import patch
import run_daily_v115 as chain
from run_daily_v103 import ROOT, read, sha, check_entry as BASE_CHECK
from run_daily_v116 import retain_recent_event_fix
from annihilation_rotation_v2 import bundle_map, install_map
from daily_weekly_repair_v2 import run_scope

WORKFLOW='ARK-WEEKLY-REPAIR-V2'


def check_entry(at=None, packet=None):
    if not packet or packet.get('workflow')!=WORKFLOW:
        raise ValueError('weekly repair binding missing')
    if packet.get('scope')!='weekly_first_clear_remaining_stamina_post_fight_daily' or packet.get('resources')!='existing_sanity_only_no_refills':
        raise ValueError('weekly repair scope differs')
    result=BASE_CHECK(at,packet)
    if sha(ROOT/packet['source_manifest'])!=packet['source_sha256']:
        raise ValueError('sealed source changed')
    source=read(ROOT/packet['source_manifest'])
    summary=source.get('run_summary',{})
    prior_report=read(ROOT/packet['source_report'])
    if (summary.get('annihilation_rotation',{}).get('status')!='weekly_failure_not_proven_new_map'
            or prior_report.get('final_daily_chains_ok') is not True
            or prior_report.get('all_cleaned') is not True
            or prior_report.get('run_summary',{}).get('run_evidence_boundary')!=summary.get('run_evidence_boundary')
            or not summary.get('run_evidence_boundary')):
        raise ValueError('source failed weekly / preserved final tail not reconciled')
    bundle=read(ROOT/packet['resource_bundle'])
    if bundle_map(bundle)['stage_id']!=packet['stage_id']:
        raise ValueError('reviewed map differs')
    return result


@contextmanager
def reporting(packet,source):
    import daily_final_report_sink_v2 as sink
    import daily_final_report_sink_v1 as presentation
    import daily_plain_popup_v1 as plain
    import daily_run_accounting_v1 as accounting
    old_sink,old_popup,old_attach=sink.reconcile_manifest,plain.summary,accounting.attach
    preserved=dict(run_id=source['run_id'],manifest=packet['source_manifest'],
                   sha256=packet['source_sha256'],effects=deepcopy(packet['preserve']))
    note='本次只续接新剿灭首通、周奖励缺口和剩余理智；此前签到及保全结果保留。战斗后再领取新增日常奖励。'
    def attach(report,manifest,*,log_paths=None):
        log=Path(report['run_summary']['run_evidence_boundary']['source'])
        paths=list(log_paths or [log.with_name('asst.bak.log'),log])
        snapshot=ROOT/packet['fight_snapshot']
        if snapshot.is_file():paths.append(snapshot)
        return old_attach(report,manifest,log_paths=paths)
    def popup(report):
        title,text,outcome=old_popup(report)
        return title,text+'\n\n'+note,outcome
    def reconcile(path,report,run_id):
        report['preserved_prior_effects']=deepcopy(preserved)
        result=old_sink(path,report,run_id)
        result['preserved_prior_effects']=deepcopy(preserved)
        presentation.write_json(Path(path),result)
        report_path=ROOT/'outputs'/f"daily_report_{report['date']}.json"
        presentation.write_json(report_path,report)
        report_path.with_suffix('.md').write_text(presentation.markdown(report)+'\n\n'+note,encoding='utf-8')
        return result
    with patch.object(sink,'reconcile_manifest',reconcile),patch.object(plain,'summary',popup),patch.object(accounting,'attach',attach):
        yield


def full(packet,source,bundle):
    import run_daily as base
    import arknights_daily_runtime_v12 as app
    import daily_workflow_identity_v1 as identity
    original=identity.boundary
    binding=dict(workflow=WORKFLOW,entrypoint=packet['entrypoint'],handoff_id=packet['handoff_id'],sha256=sha(__file__))
    with reporting(packet,source),retain_recent_event_fix(), \
         patch.object(base,'run_scope',lambda runtime:run_scope(runtime,packet,source,bundle)), \
         patch.object(identity,'boundary',lambda runtime,root,ignored:original(runtime,root,binding)), \
         patch.object(chain,'check_entry',lambda at=None,packet=None:check_entry(at,packet)):
        return chain.full(packet)


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument('--handoff',required=True)
    parser.add_argument('--check-only',action='store_true')
    args=parser.parse_args(argv)
    path=Path(args.handoff).resolve();path.relative_to(ROOT/'outputs/continuations')
    packet=read(path);check_entry(packet=packet)
    if args.check_only:
        print('PASS weekly repair V2; no game actions');return 0
    # Only before any new MAA launch, in its actual portable tree. No installed
    # AppData resource writes and no hot reload of the old daily controller.
    import arknights_daily_runtime_v12 as app
    import maa_portable_runtime_v1 as portable
    portable.bind(app)
    bundle=read(ROOT/packet['resource_bundle'])
    receipt=install_map(app,bundle)
    latch=ROOT/packet['dispatch_latch'];latch.resolve().relative_to(ROOT/'outputs/continuations')
    with latch.open('x',encoding='utf-8') as stream:
        json.dump(dict(handoff=packet['handoff_id'],at=datetime.now().astimezone().isoformat(),resource=receipt),stream,ensure_ascii=False)
    sys.argv=[str(ROOT/'run_daily.py'),'--mode','full','--existing-sanity-only']
    return full(packet,read(ROOT/packet['source_manifest']),bundle)


if __name__=='__main__':raise SystemExit(main())
