"""Candidate: anchored home numeral recognition when detection misses its box.

Only saved/current image input; no navigation, game connection, refill or
inference from an older balance. Frozen V85 reader is left untouched.
"""
import re
from contextlib import contextmanager
from unittest.mock import patch


def parse_digits(rows):
    if not rows or len(rows)!=1:return None
    raw,score=rows[0]
    text=str(raw).strip()
    # Calibrated on saved art-font frames; stricter than legacy .45 and only
    # used with an anchored home + two agreeing complete-number crops.
    if not re.fullmatch(r'\d{1,3}',text) or float(score)<.6:return None
    return dict(value=int(text),text=text,confidence=float(score))


def read_frame(path,items,recognizer):
    from PIL import Image
    import numpy as np
    with Image.open(path) as frame:
        w,h=frame.size
        names={str(t).strip() for t,x,y in items}
        # A shortcut also has the same business labels; refuse its overlay.
        if any(str(t).strip()=='首页' and 40<=x*1920/w<=280 and 250<=y*1080/h<=500
               for t,x,y in items):return None
        if '终端' not in names or len(names & {'采购中心','公开招募','任务','基建'})<2:return None
        labels=[(t,x,y) for t,x,y in items if '理智' in str(t) and '210' in str(t)
                and .54<=x/w<=.72 and .32<=y/h<=.41]
        if len(labels)!=1:return None
        rgb=frame.convert('RGB')
        proofs=[]
        # Overlapping complete-number crops, both exclude the left + control
        # and the lower denominator. Disagreement is unknown, not voting.
        for box in ((.592,.198,.694,.289),(.594,.200,.696,.292)):
            crop=rgb.crop(tuple(int(v*s) for v,s in zip(box,(w,h,w,h))))
            # Suppress the grey watermark behind the dark numeral; preserve
            # its complete glyphs instead of asking detection for a box.
            grey=np.asarray(crop.convert('L'))
            clean=np.where(grey<110,0,255).astype('uint8')
            rows,_=recognizer(np.repeat(clean[:,:,None],3,axis=2))
            parsed=parse_digits(rows)
            if parsed is None:return None
            proofs.append(parsed)
        if proofs[0]['value']!=proofs[1]['value']:return None
        return dict(value=proofs[0]['value'],source='current_labelled_home_digit_recognizer',
            crops=proofs,source_screenshot=str(path),refill_actions=0)


def install(runtime):
    original=runtime.get_stamina
    if getattr(original,'_terminal_digits_v1',False) is True:return
    def read():
        path=runtime.shot('stamina_complete_digits_current')
        items=runtime.ocr(path)
        engine=getattr(runtime,'_ocr_engine',None)
        recognizer=getattr(engine,'text_recognizer',None)
        proof=read_frame(path,items,lambda image:recognizer([image])) if recognizer else None
        if proof is None:return original()
        value=proof['value']
        checked=value if value>210 else runtime._validate_stamina_ocr_against_event_checkpoint(value)
        if checked is not None:
            runtime._RUN_SUMMARY.setdefault('stamina_digit_readings',[]).append(proof)
            runtime.log(f'  [实时理智/完整数字行] {checked}/210；本帧标签与双裁剪一致')
        return checked
    read._terminal_digits_v1=True
    read._wrapped=original
    runtime.get_stamina=read


@contextmanager
def boundary(app):
    import daily_mainline_completion_v1 as completion
    original_install=completion.install;saved=[]
    def late(runtime,*args,**kwargs):
        result=original_install(runtime,*args,**kwargs)
        saved.append(runtime.get_stamina);install(runtime)
        return result
    with patch.object(completion,'install',late):
        try:yield
        finally:
            for original in reversed(saved):app.get_stamina=original
