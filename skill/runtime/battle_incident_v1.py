"""Repeat-failure review only. Never changes MAA input, retries or outcomes."""
from contextlib import contextmanager, ExitStack
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from shutil import copyfile
from unittest.mock import patch

from ark_host.cooperation_v1 import atomic_json


def fingerprint(value):
    return sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,default=str).encode()).hexdigest()


class Review:
    """One account, mode, difficulty, stage and strategy. Called by its single controller."""
    def __init__(self,root,*,account,mode,difficulty,stage,strategy):
        if any(v is None or not str(v).strip() for v in (account,mode,difficulty,stage,strategy)):
            raise ValueError('review requires an identified encounter and strategy')
        self.key=dict(account=account,mode=mode,difficulty=difficulty,stage=stage,strategy=strategy)
        self.dir=Path(root)/'outputs/battle_reviews'/fingerprint(self.key)[:28]
        self.path=self.dir/'review.json'
        self.data=json.loads(self.path.read_text('utf-8')) if self.path.exists() else dict(
            key=self.key,failed_attempts={},captures=[],observations=[])
        if self.data['key']!=self.key:raise ValueError('review identity mismatch')

    @property
    def active(self):return len(self.data['failed_attempts'])>=2

    def save(self):
        self.dir.mkdir(parents=True,exist_ok=True)
        atomic_json(self.path,self.data)
        if self.active:
            lines=[f"# {self.key['stage']} · 高难关复盘",
                f"玩法：{self.key['mode']}；难度：{self.key['difficulty']}；同一打法已确认失败 {len(self.data['failed_attempts'])} 次。",
                "已知事实和画面如下。只看到失败结算时，具体败因仍未确认；不据此判定练度、治疗或部署有问题。"]
            for r in self.data['observations'][-12:]:
                msg=f"- {r['signal']}：{r['detail']}"
                if r.get('screenshot'): msg+=' [查看原图]('+Path(r['screenshot']).name+')'
                elif r.get('image_unavailable'):msg+='（未取得有效截图）'
                lines.append(msg)
            (self.dir/'复盘.md').write_text('\n\n'.join(lines)+'\n',encoding='utf-8')

    def observe(self,attempt,reason,*,picture=None,detail='',kind='observation'):
        """picture(target) copies an existing frame or takes one read-only capture."""
        if not attempt or not self.active:return False
        ident=fingerprint([attempt,reason])[:24]
        if any(row['id']==ident for row in self.data['observations']):return False
        row=dict(id=ident,attempt=attempt,signal=reason,detail=detail,
                 at=datetime.now().astimezone().isoformat(),kind=kind)
        if picture:
            path=self.dir/(ident+'.png')
            try:
                picture(path)
                from PIL import Image
                with Image.open(path) as im:im.verify()
                row.update(screenshot=str(path),sha256=sha256(path.read_bytes()).hexdigest())
                self.data['captures'].append(str(path))
            except Exception as exc:
                row['image_unavailable']=type(exc).__name__
                path.unlink(missing_ok=True)
        if reason=='已核实败因' and not row.get('screenshot'):
            row.update(signal='待核对的败因',detail=detail+'（没有可读的对应实图，不作为定论）')
        self.data['observations'].append(row)
        self.save()
        return True

    def result(self,attempt,outcome,*,picture=None,detail=''):
        if outcome!='confirmed_defeat' or not attempt:return False
        if attempt in self.data['failed_attempts']:return False
        self.data['failed_attempts'][attempt]=detail
        self.save()
        return self.observe(attempt,'确认战败',picture=picture,detail=detail,kind='result')


def read_only_picture(app):
    from roguelike_battle_watch_v1 import capture_adb
    return lambda path:capture_adb(app,path)


def account(app,run):
    i=app._RUN_SUMMARY.get('account_identity') or {}
    return fingerprint(i['account']) if i.get('verified') and i.get('account') else 'run:'+run


@contextmanager
def battle_trial(app,*,run,mode,difficulty,stage,strategy,attempt):
    """Bind only an explicit high-difficulty attempt. First loss never captures.
    The AI/native adapter supplies its real settlement, not a generic task end.
    """
    review=Review(app.BASE,account=account(app,run),mode=mode,difficulty=difficulty,
                  stage=stage,strategy=strategy)
    picture=read_only_picture(app)
    class Trial:
        def signal(self,reason,detail='',picture=picture):
            try:return review.observe(attempt,reason,detail=detail,picture=picture)
            except (OSError,ValueError) as exc:
                app._RUN_SUMMARY['battle_review_warning']=str(exc)
                return False
        def result(self,outcome,detail='',picture=picture):
            try:saved=review.result(attempt,outcome,picture=picture,detail=detail)
            except (OSError,ValueError) as exc:
                app._RUN_SUMMARY['battle_review_warning']=str(exc)
                return False
            if saved:
                app._RUN_SUMMARY.setdefault('battle_failure_reviews',[]).append(str(review.path))
            return saved
    trial=Trial()
    with ExitStack() as stack:
        # Reuse the battle verifier's own observations. A red flash is a
        # candidate, not an explanation of the whole failure.
        if review.active and callable(getattr(app,'_battle_has_leak',None)):
            detect=app._battle_has_leak
            def leak(frame):
                value=detect(frame)
                if value and isinstance(frame,(str,Path)):
                    trial.signal('疑似漏怪','原战斗识别命中扣减标记；该帧不单独证明失败原因。',
                                 picture=lambda dst:copyfile(frame,dst))
                return value
            stack.enter_context(patch.object(app,'_battle_has_leak',leak))
        if callable(getattr(app,'verify_battle',None)):
            verify=app.verify_battle
            def observed(*a,**kw):
                outcome=verify(*a,**kw)
                if outcome=='failed':
                    trial.result('confirmed_defeat','战斗验收返回明确战败；截图为回执后的现场。')
                return outcome
            stack.enter_context(patch.object(app,'verify_battle',observed))
        yield trial


@contextmanager
def boundary(app):
    # Shared interface for AI/MAA attempts; no watcher starts on rewards,
    # score farming, planned withdrawals or unrelated daily work.
    def bind(**identity):return battle_trial(app,**identity)
    with patch.object(app,'battle_review_trial',bind,create=True):
        yield
