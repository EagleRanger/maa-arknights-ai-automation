"""Independent progress-page adapters. No environment or exploration lifecycle.

Navigation text is tolerant; economic effect evidence is not. A module error
returns its page to the owning AI instead of closing apps or abandoning saves.
"""
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch
import hashlib
import json
import re

from ark_modules.core import ReceiptStore
from navigation_text_v1 import key, same_label, Target, recover, crop_read
from operator_optional_inspection_v1 import frame

ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Theme:
    title: str
    rewards: str
    growth: str = ''
    complete: tuple = ()
    currency: str = ''
    total: int = 0


THEMES = {
    'Phantom': Theme('傀影与猩红孤钻', '古堡笔记', '幕后筹备', ('准备就绪',)),
    'Mizuki': Theme('水月与深蓝之树', '生态谱系', '认知塑造', ('认知完备',)),
    'Sami': Theme('探索者的银凇止境', '科考记录', '文化比较', ('研究完成',)),
    'Sarkaz': Theme('萨卡兹的无终奇语', '假说辑录', '历史重构', currency='散佚迷思', total=78),
    'JieGarden': Theme('岁的界园志异', '游园纪念', '学识古今', currency='失落智识', total=71),
    'BlackFlow': Theme('沉沦者的黑流树海', '源流堆栈', '生命游戏', currency='演化算子', total=67),
    'Reclamation': Theme('沙洲遗闻', '繁荣馈赠'),
}


def contains(rows, text):
    return any(key(text) in key(t) for t, x, y in rows)


def positions(rows, text, rect=(0,0,1920,1080)):
    l,t,r,b = rect
    return [(int(x),int(y)) for label,x,y in rows if l<=x<=r and t<=y<=b
            and (same_label(str(label).rstrip('>＞»›》 '), text, contextual=True) or
                 re.fullmatch(r'(?:lv)?\d+' + re.escape(key(text)),key(label)))]


def theme_home(rows, theme):
    p = THEMES[theme]
    if theme=='JieGarden' and all(contains(rows,s) for s in ('界园志异','请君入园','特勤干员培训')):
        return True
    reward = contains(rows, p.rewards)
    # The reward title alone also exists on the reward page. Require a second
    # independent home control, not an arbitrary text mismatch percentage.
    other = any(contains(rows, label) for label in
                ('开始探索','继续探索','常规行动','请君入园','进入探索',
                 '开始演算','继续演算',p.growth,*p.complete) if label)
    return reward and other and not contains(rows, '确认升级')


def reward_state(rows, theme):
    """Pure recognizer used both by the live consumer and fixture replay."""
    labels = [key(t) for t,x,y in rows]
    p = THEMES[theme]
    if theme=='Reclamation':
        from reclamation_rewards_state_v1 import state
        exchange=state(rows)
        return dict(page=exchange['page'],pending=0 if exchange['no_exchange_now'] else None,
                    claimed=0,claim_buttons=[],exchange=exchange)
    page = (contains(rows,p.rewards) or contains(rows,'购买等级')) and not theme_home(rows,theme)
    if theme=='BlackFlow' and contains(rows,'如何提升等级') and contains(rows,'距离解码进展'):
        page=True
    pending = sum(t == key('可领取') for t in labels)
    claimed = sum(t == key('已领取') for t in labels)
    buttons = positions(rows,'一键领取') or positions(rows,'全部领取')
    return dict(page=page,pending=pending,claimed=claimed,claim_buttons=buttons)


def verified_reward_effect(before, after):
    if not before['page'] or not after['page']:return False
    return (before['pending'] > after['pending'] or after['claimed'] > before['claimed'])


def card_entries(rows, title_x, *, reclamation=False):
    buttons=positions(rows,'进入主题',(0,780,1920,1080))
    if not reclamation:buttons=[p for p in buttons if title_x<=p[0]<=title_x+350]
    return sorted(buttons,key=lambda p:abs(p[0]-title_x))


def growth_state(rows, theme):
    """Counters are exact and region-bound; absent OCR is not zero."""
    p=THEMES[theme]
    fractions=[(int(a),int(b)) for text,x,y in rows if x<500 and y>600
               for a,b in re.findall(r'(\d+)\s*[/／]\s*(\d+)',str(text))]
    values={int(str(t).strip()) for t,x,y in rows
            if x>1600 and y<100 and re.fullmatch(r'\d+',str(t).strip())}
    progress=next((a for a,b in fractions if b==p.total),None)
    return dict(page=bool(p.currency and contains(rows,p.currency) and progress is not None),
                progress=progress,total=p.total,points=next(iter(values)) if len(values)==1 else None)


@contextmanager
def isolated(app):
    def denied(*args, **kwargs):
        raise RuntimeError('progress-only module cannot start business, abandon saves or close environment')
    names = ('main','mode_full','mode_daily','mode_roguelike','mode_reclamation',
             'run_maa','run_maa_copilot','run_maa_daily_tasks','cleanup_after_task',
             '_mizuki_abandon_active_exploration_for_verification',
             '_reset_owned_reclamation_temporary_save', '_run_maa_core_roguelike_once')
    with ExitStack() as stack:
        for name in names:
            if callable(getattr(app,name,None)):stack.enter_context(patch.object(app,name,denied))
        yield


class ProgressUI:
    def __init__(self, app, theme, output):
        self.app,self.theme,self.out = app,theme,Path(output)
        self.pages=[]; self.actions=[]

    def capture(self, tag):
        row=frame(self.app,self.out/'frames',f'{len(self.pages):03d}-{tag}')
        self.pages.append(row);return row

    def tap(self, point, reason):
        if self.app._maa_task_queue_running() is not False:raise RuntimeError('queue busy')
        self.app.tap(*point);self.actions.append(dict(point=point,reason=reason));self.app.wait(2)

    def locate(self, row, label, rect=(0,0,1920,1080)):
        if self.theme=='JieGarden' and theme_home(row['items'],self.theme):
            if label=='学识古今':
                hits=positions(row['items'],'学识',(0,350,500,700))
                if len(hits)==1:return (int(hits[0][0])+80,int(hits[0][1]))
            if label=='游园纪念':rect=(1600,20,1900,135)
        hits=positions(row['items'],label,rect)
        if len(hits)==1:return hits[0]
        if len(hits)>1:raise RuntimeError('ambiguous navigation label: '+label)
        rows=recover(self.app,row['screenshot'],row['items'],Target(label,rect),self.app.ocr,
                     lambda rows:theme_home(rows,self.theme))
        hits=positions(rows,label,rect)
        if not hits and self.theme=='JieGarden' and label=='游园纪念' and theme_home(row['items'],self.theme):
            # Confirmed layout: ornate title can OCR as its pinyin line. Three
            # independent home anchors bind this stable reward card, not text.
            return (1745,65)
        return hits[0] if len(hits)==1 else None

    def navigate(self):
        row=self.capture('entry')
        if theme_home(row['items'],self.theme):return row
        # Known progress pages return locally. Do not feed a normal theme
        # carousel to legacy goto_main_menu's 120-second unknown-page watcher.
        for _ in range(6):
            rows=row['items']
            if theme_home(rows,self.theme):return row
            rogue_cards=any(contains(rows,p.rewards) for k,p in THEMES.items() if k!='Reclamation')
            carousel=(positions(rows,'进入主题') or contains(rows,'正在游玩其他主题'))
            ra_list=contains(rows,'沙洲遗闻') and contains(rows,'重启锚点')
            if self.theme!='Reclamation' and rogue_cards and carousel:break
            if self.theme=='Reclamation' and ra_list and carousel:break
            if all(contains(rows,s) for s in ('集成战略','生息演算','查看全部主题')):
                rect=(1000,0,1920,1080) if self.theme=='Reclamation' else (0,0,1000,1080)
                point=self.locate(row,'查看全部主题',rect)
                if not point:raise RuntimeError('theme list entry needs AI')
                self.tap(point,'open only requested theme family')
            elif contains(rows,'终端') and (contains(rows,'编队') or contains(rows,'公开招募')):
                self.tap(self.locate(row,'终端'),'open terminal from verified ordinary home')
            elif contains(rows,'ATTENTION') or contains(rows,'TO-DO LIST'):
                self.tap((1435,1000),'verified terminal long-term tab')
            elif (carousel or any(theme_home(rows,k) for k in THEMES)
                  or any(reward_state(rows,k)['page'] for k in THEMES)
                  or (contains(rows,'幕后筹备') and contains(rows,'当前加成总览'))
                  or any(growth_state(rows,k)['page'] for k in THEMES if THEMES[k].currency)):
                self.tap(self.app.POS_BACK,'return one known theme level, preserve exploration')
            else:raise RuntimeError('local navigation needs AI; no generic long wait')
            row=self.capture('navigation')
        else:raise RuntimeError('theme navigation step budget')
        # Card selection is bound to its title, not the first Enter button.
        for index in range(12):
            row=self.capture('themes')
            # Current theme selector keeps the active theme's big title above
            # a scrolling row. Use the reward-track heading on the actual card
            # instead; the unchanged header is not the selected card identity.
            titles=[(x,y) for t,x,y in row['items']
                    if 540<=y<=760 and same_label(t,THEMES[self.theme].rewards,contextual=True)]
            if self.theme=='Reclamation':
                titles=[(x,y) for t,x,y in row['items'] if key(THEMES[self.theme].title) in key(t)]
            if titles:
                tx,ty=titles[0]
                if self.theme=='Reclamation':
                    self.tap((int(tx),int(ty)),'select existing reclamation theme, preserve save')
                    row=self.capture('theme_selected')
                # Reward heading is left, Enter right; nearest alone crosses cards.
                near=card_entries(row['items'],tx,reclamation=self.theme=='Reclamation')
                if not near and self.theme!='Reclamation' and tx>1550 and positions(row['items'],'进入主题'):
                    self.app.swipe(1250,850,650,850,700);self.app.wait(1)
                    continue  # Visible title but Enter is off-screen: reveal this card.
                valid_ra=self.theme=='Reclamation' and len(near)==1 and contains(row['items'],'沙洲遗闻')
                if not near or (not valid_ra and abs(near[0][0]-tx)>350):
                    if contains(row['items'],'正在游玩其他主题'):
                        raise RuntimeError('another active exploration locks this theme; save preserved')
                    raise RuntimeError('theme button not bound to card')
                self.tap(near[0],'enter '+self.theme);self.app.wait(3)
                row=self.capture('theme_home')
                row=self.entry_overlays(row)
                if theme_home(row['items'],self.theme):return row
                retry=positions(row['items'],'进入主题',(0,780,1920,1080))
                retry=[p for p in retry if abs(p[0]-near[0][0])<100]
                if len(retry)==1 and contains(row['items'],THEMES[self.theme].rewards):
                    self.tap(retry[0],'selected card needs second confirmed enter action')
                    self.app.wait(3);row=self.capture('theme_home_retry')
                    row=self.entry_overlays(row)
                    if theme_home(row['items'],self.theme):return row
                raise RuntimeError('theme home needs AI; no exploration or save reset')
            if not (positions(row['items'],'进入主题') or contains(row['items'],'正在游玩其他主题')):
                raise RuntimeError('theme carousel not confirmed')
            # A full sweep in both directions; short overlapping moves keep
            # titles on-screen instead of skipping intermediate cards.
            order=list(THEMES)
            visible=[order.index(k) for k,p in THEMES.items() if k!='Reclamation'
                     and any(540<=y<=760 and same_label(t,p.rewards,contextual=True) for t,x,y in row['items'])]
            newer=bool(visible and order.index(self.theme)>max(visible))
            older=bool(visible and order.index(self.theme)<min(visible))
            start,end=((650,850),(1250,850)) if older or (not newer and index<4) else ((1250,850),(650,850))
            self.app.swipe(*start,*end,700);self.app.wait(1)
        raise RuntimeError('requested theme not visible in bounded carousel sweep')

    def entry_overlays(self,row):
        """Only the freshly entered theme's intro; never starts exploration."""
        for _ in range(5):
            if theme_home(row['items'],self.theme):return row
            if contains(row['items'],'是否跳过剧情'):
                self.tap((1196,542),'confirm skip of theme introduction')
            elif any('跳过' in str(t) and x>1500 and y<150 for t,x,y in row['items']):
                self.tap((1758,79),'skip theme introduction')
            elif len(row['items'])<5:self.app.wait(1)
            else:return row
            row=self.capture('entry_overlay')
        return row

    def back_to_theme(self):
        for attempt in range(3):
            row=self.capture('return_home')
            if theme_home(row['items'],self.theme):return True
            self.tap(self.app.POS_BACK,'return from owned progress page')
        return theme_home(self.capture('return_last')['items'],self.theme)

    def rewards(self):
        home=self.navigate();point=self.locate(home,THEMES[self.theme].rewards)
        if not point:raise RuntimeError('reward entry needs AI')
        self.tap(point,'open independent rewards')
        row=self.capture('rewards_before');before=reward_state(row['items'],self.theme)
        if not before['page']:raise RuntimeError('reward page identity needs AI')
        if self.theme=='Reclamation' and not before['exchange']['no_exchange_now']:
            raise RuntimeError('prosperity-point exchange needs AI item selection; not a one-click level reward')
        if before['pending']==0:
            again=self.capture('rewards_empty_confirm');after=reward_state(again['items'],self.theme)
            if not after['page'] or after['pending'] or not (after['claimed'] or not after['claim_buttons']):
                raise RuntimeError('no pending reward not yet evidenced')
            return dict(ok=True,status='verified_no_claimable',claimed_new=0,before=before,after=after,
                        home_confirmed_after=self.back_to_theme())
        if len(before['claim_buttons'])!=1:raise RuntimeError('pending reward action needs AI')
        self.tap(before['claim_buttons'][0],'claim only confirmed free pending rewards')
        for i in range(8):
            row=self.capture('reward_after');after=reward_state(row['items'],self.theme)
            if after['page']:
                if not verified_reward_effect(before,after):raise RuntimeError('claim effect unchanged; do not click twice')
                return dict(ok=True,status='verified_claim_effect',before=before,after=after,
                            home_confirmed_after=self.back_to_theme())
            from reward_transition_v1 import outfit_layer
            text=' '.join(str(t) for t,x,y in row['items'])
            layer=outfit_layer(row['items'],text)
            if layer:self.tap(layer['position'] or self.app.POS_DISMISS,'close reward reveal')
            elif any(contains(row['items'],s) for s in ('获得物资','首次获得','获得奖励')):
                self.tap(self.app.POS_DISMISS,'close confirmed reward overlay')
            else:raise RuntimeError('unknown reward transition; preserve page for AI')
        raise RuntimeError('reward transition limit; preserve page for AI')

    def growth(self):
        home=self.navigate();profile=THEMES[self.theme]
        for label in profile.complete:
            if contains(home['items'],label):
                return dict(ok=True,status='verified_complete_skipped',complete_marker=label,
                            upgrades=[],home_confirmed_after=True)
        if not profile.growth:raise RuntimeError('new theme growth layout requires live adapter')
        # Reuse proven growth consumers but replace their broad navigation with
        # this progress-only entry. No old abandon/exploration side effect.
        if self.theme=='Phantom':
            with patch.object(self.app,'navigate_to_phantom_home',lambda **kw:dict(ok=True)):
                result=self.app.apply_phantom_preparation_points()
        elif self.theme=='Mizuki':
            with patch.object(self.app,'navigate_to_mizuki_home',lambda **kw:dict(ok=True)):
                result=self.app.apply_mizuki_cognition_points()
        elif self.theme=='Sami':
            import run_sami_until_deadline as sami
            from sami_culture_complete_v1 import boundary
            with patch.object(sami,'ark',self.app), boundary(sami):result=sami.service_culture()
        else:
            point=self.locate(home,profile.growth)
            if not point:raise RuntimeError('new growth entry needs AI')
            self.tap(point,'inspect new growth layout without spending')
            observations=[]
            for _ in range(2):
                row=self.capture('new_growth_layout')
                enlarged=crop_read(self.app,row['screenshot'],(1580,5,1900,160))
                if not any(re.fullmatch(r'\d+',str(t).strip()) and y<100 for t,x,y in enlarged):
                    from ocr_tolerance_v1 import line_items
                    enlarged+=line_items(self.app,row['screenshot'],(1710,35,1800,95),3)
                row['currency_crop_items']=enlarged
                observations.append(growth_state(row['items']+enlarged,self.theme))
            if all(s['page'] and s['points']==0 for s in observations):
                return dict(ok=True,status='verified_no_points',upgrades=[],observations=observations,
                            home_confirmed_after=self.back_to_theme())
            if all(s['page'] and s['progress']==profile.total for s in observations):
                return dict(ok=True,status='verified_complete',upgrades=[],observations=observations,
                            home_confirmed_after=self.back_to_theme())
            raise RuntimeError('growth candidate selection needs AI; page preserved, no upgrade submitted')
        return dict(result,home_confirmed_after=self.back_to_theme())


def run(app, theme, action, output):
    if theme not in THEMES or action not in ('inspect','rewards','growth'):
        raise ValueError('explicit supported theme and operation required')
    if theme=='Reclamation' and action=='growth':raise ValueError('reclamation is rewards-only')
    ui=ProgressUI(app,theme,output)
    result=dict(theme=theme,operation=action,battle_invoked=False,daily_invoked=False,
                cleanup_invoked=False,source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    try:
        if app._maa_task_queue_running() is not False:raise RuntimeError('queue owns device')
        with isolated(app):
            if action=='inspect':
                row=ui.navigate();value=dict(ok=True,status='theme_home_verified',home_confirmed_after=True)
            else:value=getattr(ui,action)()
        result.update(value)
        if action=='rewards' and 'before' in result and 'after' in result:
            result.update(pending_before=result['before']['pending'],pending_after=result['after']['pending'])
    except Exception as exc:
        result.update(ok=False,status='needs_ai',reason=str(exc),environment_preserved=True)
    result.update(pages=ui.pages,actions=ui.actions)
    ReceiptStore(Path(output)/'result.json').save(result)
    return result
