"""Mechanical file-command bridge for the existing single-owner test host.

The execution AI chooses an action, not a frame counter or PTY protocol.
Malformed commands are rejected locally, never fed into business/cleanup.
"""
import json
from pathlib import Path
import time
from uuid import uuid4

ACTIONS={'observe','tap','back','swipe','home','mastery','event','committee','wait','end'}


def admit(command,receipt):
    row=dict(command);action=row.get('action')
    if action not in ACTIONS:raise ValueError('unsupported acceptance action')
    if action not in {'observe','end'}:
        frames=receipt.get('frames') or []
        if not frames:raise ValueError('wait for the first actual frame')
        row['seq']=frames[-1]['seq']
        row.setdefault('reason','explicit module acceptance: '+action)
    if action=='tap':
        point=row.get('point')
        if not isinstance(point,list) or len(point)!=2 or any(type(i) is not int for i in point):
            raise ValueError('two integer guest coordinates required')
        if not 0<=point[0]<1920 or not 0<=point[1]<1080:raise ValueError('point outside guest frame')
    if action=='swipe':
        for key in ('start','end'):
            admit(dict(action='tap',point=row.get(key)),receipt)
    return row


def submit(output,command):
    output=Path(output);receipt=json.loads((output/'receipt.json').read_text('utf-8'))
    if receipt.get('finished_at'):raise ValueError('acceptance session has ended')
    row=admit(command,receipt)
    directory=output/'commands';directory.mkdir(parents=True,exist_ok=True)
    if any(json.loads(p.read_text('utf-8')).get('status')=='dispatched'
           for p in directory.glob('*.ack.json')):
        raise ValueError('current command still executing; inspect its result before another action')
    path=directory/(str(time.time_ns())+'-'+uuid4().hex[:8]+'.json')
    path.write_text(json.dumps(row,ensure_ascii=False),encoding='utf-8')
    return path


class Commands:
    def __init__(self,output,*,seconds=1200,clock=time.monotonic,sleep=time.sleep):
        self.output=Path(output);self.clock=clock;self.sleep=sleep
        self.deadline=clock()+seconds;self.seen=set();self.previous=None
        (self.output/'commands').mkdir(parents=True,exist_ok=True)

    def __iter__(self):return self

    def __next__(self):
        if self.previous:
            self.previous.with_suffix('.ack.json').write_text(json.dumps({'status':'returned'}),encoding='utf-8')
            self.previous=None
        while self.clock()<self.deadline:
            for path in sorted((self.output/'commands').glob('*.json')):
                if path.name.endswith('.ack.json') or path in self.seen:continue
                self.seen.add(path)
                try:
                    data=json.loads(path.read_text('utf-8'))
                    receipt=json.loads((self.output/'receipt.json').read_text('utf-8'))
                    row=admit(data,receipt)
                except (OSError,ValueError,TypeError,KeyError) as exc:
                    path.with_suffix('.ack.json').write_text(json.dumps(dict(status='rejected',error=str(exc))),encoding='utf-8')
                    print('ARK_MODULE_COMMAND_REJECTED '+str(path),flush=True)
                    continue
                path.with_suffix('.ack.json').write_text(json.dumps({'status':'dispatched'}),encoding='utf-8')
                self.previous=path
                return json.dumps(row,ensure_ascii=False)+'\n'
            self.sleep(.25)
        if self.deadline:
            self.deadline=0
            return '{"action":"end"}\n'  # normal owner cleanup, not a killed process.
        raise StopIteration
