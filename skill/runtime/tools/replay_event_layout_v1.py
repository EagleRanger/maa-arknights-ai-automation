"""Read one retained screenshot with the daily OCR/profile. No game or outbox."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

def replay(image, stage, event, app):
    import event_layout_profiles_v1 as profiles
    rows=app.ocr(str(image))
    obs=profiles.inspect_frame(image,rows,event,stage)
    p=profiles.PROFILES.get(obs['profile'])
    reading=profiles.price(obs,image,rows,app._ocr_engine.text_recognizer) if p else None
    ratio=p.badges(image) if p else None
    return dict(target=stage,observations=obs,three_badges=None if ratio is None else ratio>=.08,
                badge_ratio=ratio,price=reading,game_actions=0)

def main():
    import arknights_daily_runtime_v12 as app
    from local_ocr_v6_small_v2 import boundary
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--image',required=True,type=Path)
    ap.add_argument('--stage',required=True)
    ap.add_argument('--event')
    ap.add_argument('--internal',help='stageId from this activity catalog')
    args=ap.parse_args()
    if not args.image.is_file():ap.error('找不到截图')
    event={}
    if args.event:event['name']=args.event
    if args.internal:event['stages']=[dict(display=args.stage,internal=args.internal)]
    with boundary(app):
        result=replay(args.image,args.stage,event,app)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['observations']['profile'] else 2

if __name__=='__main__':
    raise SystemExit(main())
