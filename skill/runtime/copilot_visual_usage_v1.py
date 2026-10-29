"""Report confirmed EX gross sanity deductions separately from native Fight ledger."""
from contextlib import contextmanager
from copy import deepcopy
from unittest.mock import patch
import re,hashlib
from pathlib import Path


def detail_cost(path,items,engine):
    codes={m[1] for t,x,y in items if x>1200 and 90<y<230
        if (m:=re.fullmatch(r'(?:O?PERATION\s+)?(YW-EX-[1-8])',str(t).strip().rstrip("'’′`")))}
    actions=[str(t).strip() for t,x,y in items if x>1500 and 930<y<1030 and str(t).strip() in ('开始行动','开始突袭')]
    costs={int(m[1]) for t,x,y in items if x>1600 and y>1000 if (m:=re.fullmatch(r'[-−]\s*(\d{1,3})',str(t).strip()))}
    if len(codes)!=1 or len(actions)!=1 or len(costs)!=1:return None
    import cv2,numpy as np
    frame=cv2.imdecode(np.fromfile(str(path),np.uint8),1)
    if frame is None or frame.shape[:2]!=(1080,1920):return None
    roi=cv2.cvtColor(frame[1008:1066,1710:1880],cv2.COLOR_BGR2GRAY)
    rows,_=engine.text_recognizer([cv2.cvtColor(cv2.resize(v,None,fx=4,fy=4),cv2.COLOR_GRAY2BGR)
        for v in (roi,cv2.normalize(roi,None,0,255,cv2.NORM_MINMAX))])
    read=[int(m[1]) for t,s in rows if s>=.8 if (m:=re.fullmatch(r'[-−]\s*(\d{1,3})',str(t).strip()))]
    cost=next(iter(costs))
    if len(read)!=2 or any(n!=cost for n in read) or cost<=0:return None
    return dict(stage=next(iter(codes)),mode='challenge' if actions[0]=='开始突袭' else 'normal',
        gross_cost=cost,evidence=str(path),evidence_sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest().upper())


def lines(report):
    rows=(report.get('run_summary') or {}).get('copilot_visual_usage') or []
    return [f"已核实开荒理智：{r['stage']}{'突袭' if r['mode']=='challenge' else '普通'}1次，扣除{r['gross_cost']}理智（开战价格与真实战后徽记闭环）。" for r in rows]


@contextmanager
def boundary(app):
    import daily_plain_popup_v1 as plain
    import daily_run_accounting_v1 as accounting
    import daily_final_report_sink_v1 as presentation
    shot,clear,attach,popup,effects=app.shot,app.clear_event_stage,accounting.attach,plain.summary,presentation.effect_lines
    observed=[]
    def capture(*args,**kwargs):
        path=shot(*args,**kwargs)
        if args and args[0]=='before_start':
            proof=detail_cost(path,app.ocr(path),app._ocr_engine)
            if proof:observed.append(proof)
        return path
    def cleared(event,stage,*args,**kwargs):
        start=len(observed);before=app._CURRENT_RUN_LAST_STAMINA_BATTLE_AT
        value=clear(event,stage,*args,**kwargs)
        mode=kwargs.get('mode',args[0] if args else 'normal')
        matches=[r for r in observed[start:] if r['stage']==stage['display'] and r['mode']==mode]
        after=app._CURRENT_RUN_LAST_STAMINA_BATTLE_AT
        if value is True and after!=before and len(matches)==1:
            row=dict(matches[0],battle_closed_at=after.isoformat(),verified=True)
            app._RUN_SUMMARY.setdefault('copilot_visual_usage',[]).append(row)
        return value
    def attached(report,manifest,**kwargs):
        result=attach(report,manifest,**kwargs)
        result['copilot_visual_usage']=deepcopy((report.get('run_summary') or {}).get('copilot_visual_usage') or [])
        return result
    def summary(report):
        title,text,status=popup(report);extra=lines(report)
        if extra:
            text='\n'.join(line for line in text.splitlines() if line!='理智作战：没有可确认的完成记录。')
            text+='\n'+'\n'.join(extra)
        return title,text,status
    with patch.object(app,'shot',capture),patch.object(app,'clear_event_stage',cleared), \
         patch.object(accounting,'attach',attached),patch.object(plain,'summary',summary), \
         patch.object(presentation,'effect_lines',lambda report:effects(report)+lines(report)):
        yield
