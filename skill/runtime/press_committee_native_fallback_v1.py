"""This activity only: native missing-plan fallback and known paper return."""
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
import json
import re
import event_press_committee_v2 as daily
import press_committee_pages_v2 as pages
import maa_utility_custom_v1 as utility
STRICT_PAPER = pages.paper


def visual_paper(row):
    """Five actual pager dots identify order; printed paper titles are optional."""
    import cv2,numpy as np
    try:
        source=cv2.imdecode(np.fromfile(str(row['screenshot']),dtype=np.uint8),1)
    except (OSError,KeyError):return None
    if source is None or source.shape[:2]!=(1080,1920):return None
    values=[]
    for x in (867,914,960,1006,1052):
        crop=source[871:880,x-4:x+5]
        if float(np.mean(crop.max(axis=2)-crop.min(axis=2)))>12:return None
        values.append(float(crop.mean()))
    selected=max(range(5),key=lambda i:values[i]);others=[v for i,v in enumerate(values) if i!=selected]
    if (values[selected]<205 or not all(65<v<185 for v in others)
            or max(others)-min(others)>30 or values[selected]-max(others)<50):return None
    return pages.PAPERS[selected]


def one_edit(left,right):
    if abs(len(left)-len(right))>1:return False
    if len(left)==len(right):return sum(a!=b for a,b in zip(left,right))<=1
    if len(left)>len(right):left,right=right,left
    for index,(a,b) in enumerate(zip(left,right)):
        if a!=b:return left[index:]==right[index+1:]
    return True


def paper(row):
    observed=visual_paper(row)
    if observed:return observed
    exact=STRICT_PAPER(row)
    if exact:return exact
    # The actual third-paper title read 乡士报, while the UI and its English
    # subtitle identify 乡土报. Within this title ROI allow one OCR edit only,
    # and only when it selects exactly one of this event's five identities.
    hits=set()
    for text,x,y in row['items']:
        if 500<x<1250 and 600<y<720:
            value=re.sub(r'[^\u4e00-\u9fff]','',str(text))
            hits.update(name for name in pages.PAPERS if one_edit(value,name))
    return next(iter(hits)) if len(hits)==1 else None


def normalize_home_account(rows):
    # Page identity and account digits are separate. Correct only the observed
    # RHODES ID label's I/T typography error, never invent or replace digits.
    from account_progress_v1 import uid_from_items
    if uid_from_items(rows):
        return rows
    regions={'采购中心':(1080,600,1420,825),'公开招募':(1380,650,1660,840),
             '基建':(1320,780,1680,1040),'仓库':(1650,800,1910,1060),
             '干员':(1330,410,1650,610),'编队':(1000,410,1320,620)}
    hits=set()
    for t,x,y in rows:
        label=str(t).replace(' ','')
        if label in regions:
            a,b,c,d=regions[label]
            if a<=x<=c and b<=y<=d:hits.add(label)
    if len(hits)<4:return rows
    found=[]
    for t,x,y in rows:
        if 0<=x<=500 and 560<=y<=720:
            text=re.sub(r'\s+','',str(t)).upper()
            match=re.fullmatch(r'(?:RHODES|RHODE|HODES|HODE)[I1LT]?D[:：]?(\d{6,12})',text)
            if match:found.append((match[1],x,y))
    if len({value for value,x,y in found})!=1:return rows
    value,x,y=found[0]
    return list(rows)+[('UID:'+value,x,y)]


def known_return_page(row):
    text = ''.join(str(t) for t, x, y in row['items'])
    lobby = '战时新闻委员会' in text and '作战结束时间' in text
    terminal = (any(str(t) == '终端' and y > 900 for t, x, y in row['items'])
                and any(key in text for key in ('MAIN', '全部完成', '集成战略')))
    return bool(pages.paper(row) or lobby or terminal)


def stable(app,out,tag):
    for attempt in range(3):
        row=pages.frame(app,out,tag+'-'+uuid4().hex[:8])
        if visual_paper(row) or row['items']:return row
        if attempt<2:app.wait(.5)
    return row


def turn(app,row,direction,out):
    before=paper(row)
    point=pages.match(app,row,'NextPage',
        (1115,271,104,122) if direction=='right' else (60,271,104,122),mirror=direction=='left')
    if not point:return None
    app.tap(*point)
    for attempt in range(3):
        app.wait(.5)
        after=stable(app,out,'page-'+direction)
        if paper(after) and paper(after)!=before:return after
    return None


@contextmanager
def page_boundary():
    with patch.object(pages,'paper',paper),patch.object(pages,'stable',stable),patch.object(pages,'turn',turn):
        yield


def native_available(app):
    path = Path(app.MAA_ROOT) / 'resource/tasks/MiniGame/WartimePressCommittee.json'
    try:
        tasks = json.loads(path.read_text('utf-8-sig'))
        return all('MiniGame@WartimePressCommittee@' + key in tasks
                   for key in ('Begin', 'Day4', 'Day5', 'EnterDay4', 'EnterDay5'))
    except (OSError, ValueError):
        return False


def solve_missing_plan(app, output, target, original):
    try:
        result = original(app, output, target=target)
    except FileNotFoundError as exc:
        # A recipient may have no private learned-layout file at all. Missing
        # unrelated files are still genuine faults, never a solve permission.
        expected=(Path(app.BASE)/pages.PLAN).resolve()
        if not exc.filename or Path(exc.filename).resolve()!=expected or target not in pages.PAPERS:
            raise
        result=dict(status='needs_ai_layout_plan',paper=target)
    if result.get('status') != 'needs_ai_layout_plan' or not native_available(app):
        return result
    if app._maa_task_queue_running() is not False:
        return dict(result, status='deferred_active_queue')
    out = Path(output)
    row = pages.stable(app, out, 'before-native')
    if pages.paper(row)!=target:
        row=pages.go(app,row,target,out)
    before = pages.describe(app, row)
    if before.get('paper') != target or before.get('status') != 'unlocked':
        return dict(result, status='native_precondition_unverified', before=before)
    native = utility.run(app, 'committee', out / 'native', timeout=300)
    if native.get('status') != 'native_completed_effect_pending':
        return dict(result, status='native_effect_unverified', native=native)
    # Native Begin may advance to tomorrow's locked page. Return to the named
    # target for actual reward checks rather than crediting its task callback.
    row = pages.go(app, pages.open_page(app, out), target, out)
    after = pages.describe(app, row)
    return dict(status='paper_returned_verify_claims' if after.get('status') == 'verified_complete'
                else 'native_effect_unverified', paper=target, before=before, after=after, native=native)


def service(app, original, output=None):
    original_home, original_solve, original_ocr = app.goto_main_menu, pages.solve, app.ocr
    out = Path(output or Path(app.OUTPUT_DIR) / 'press_committee' / uuid4().hex)
    def home():
        row = pages.stable(app, out / 'entry-return', 'page')
        if known_return_page(row):
            return (app._maa_task_queue_running() is False
                    and pages.return_home(app, out / 'entry-return'))
        return original_home()
    def solve(port, destination, target=None):
        return solve_missing_plan(port, destination, target, original_solve)
    def read(*args,**kwargs):
        rows=normalize_home_account(original_ocr(*args,**kwargs))
        # Only a known home layout missing its data label needs a line re-read.
        # Do not run full-frame detection again or demand a perfect brand word.
        from ocr_tolerance_v1 import navigation_home,line_items
        from account_progress_v1 import uid_from_items
        if args and navigation_home(rows) and not uid_from_items(rows):
            rows=list(rows)+line_items(app,args[0],(0,622,320,672))
        return rows
    with patch.object(app, 'goto_main_menu', home), patch.object(pages, 'solve', solve),page_boundary(), \
         patch.object(app,'ocr',read):
        return original(app, output=output)


@contextmanager
def boundary(app):
    original = daily.service
    def adapted(port, output=None):
        return service(port, original, output)
    with patch.object(daily, 'service', adapted):
        yield
