"""Quarantine the proven stalled exact job; prefer safe delegation, no blind retry."""
import hashlib,json
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import patch

STALLED='CEAE7CFE4020A3EB7327CB997F8FBE77F52082EAF134E0FB767E4339AF3A0107'


class SSSDeferred(BaseException):pass


@contextmanager
def boundary(app):
    old_run,old_security=app.run_sss_copilot,app.mode_security
    def run(region,*args,**kwargs):
        if region!='日达诺夫园区':return old_run(region,*args,**kwargs)
        path,_=app._select_sss_job(region,allow_online=False)
        if not path or hashlib.sha256(Path(path).read_bytes()).hexdigest().upper()!=STALLED:
            return old_run(region,*args,**kwargs)
        from sss_delegate_live_v2 import execute
        result=execute(app,dict(region=region))
        app._RUN_SUMMARY.setdefault('sss_exact_job_recovery',[]).append(result)
        if result.get('status')=='delegation_verified':return True
        if not result.get('home_verified'):
            app._event_page_attention('sss_delegate_return_unverified',observations=[result])
        if result.get('status')=='card_reserve_boundary' and result.get('home_verified'):
            print('保全后续清理等待可支配代理卡；周一5张预留不动，本次不重复已知卡死作业。',flush=True)
        else:
            print('[PROJECT_ATTENTION_NOW] '+json.dumps(dict(reason='known_sss_job_deferred',
                status=result.get('status'),old_job_sha256=STALLED,home_verified=result.get('home_verified')),ensure_ascii=False),flush=True)
        raise SSSDeferred()
    def security(*args,**kwargs):
        try:return old_security(*args,**kwargs)
        except SSSDeferred:
            app._RUN_SUMMARY.setdefault('security',{}).update(status='partial',reason='known_stalled_job_no_unchanged_retry_card_reserve_retained')
            return False
    with patch.object(app,'run_sss_copilot',run),patch.object(app,'mode_security',security):yield
