"""Small shared capture/identify/verified-transition loop, using existing OCR.

No background polling. Each invocation is bounded; only file paths/text are
retained. A transition must be registered with source and destination identity.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from .core import Result


@dataclass(frozen=True)
class Frame:
    path: str
    captured_at: datetime
    items: tuple
    kind: str
    positions: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Transition:
    source: str
    target: str
    action: object
    precondition: object = lambda frame: True


class Vision:
    def __init__(self, port, classify, transitions=(), *, max_frames=5, max_actions=3):
        if not 1 <= max_frames <= 8 or not 0 <= max_actions <= 5:
            raise ValueError('bounded recognition budget required')
        self.port, self.classify = port, classify
        self.transitions = tuple(transitions)
        self.max_frames, self.max_actions = max_frames, max_actions

    def read(self, tag):
        paths = []
        for n in range(self.max_frames):
            path, at = self.port.capture(f'{tag}_{n}')
            if at.tzinfo is None or not 0 <= (self.port.now() - at).total_seconds() <= 5:
                raise ValueError('stale capture')
            values = tuple(self.port.ocr(path))
            kind, positions = self.classify(values)
            paths.append(str(path))
            frame = Frame(str(path), at, values, kind, positions or {})
            if kind != 'transition':
                return frame, tuple(paths)
            if n + 1 < self.max_frames: self.port.wait(1)
        return frame, tuple(paths)

    def reach(self, target):
        evidence, seen = [], set()
        for attempt in range(self.max_actions + 1):
            # Even a screenshot backend can pause an emulator; the supplied
            # adapter below uses the project's read-only ADB backend explicitly.
            frame, paths = self.read('module_page')
            evidence.extend(paths)
            if frame.kind == target:
                return Result('succeeded', '目标页面已由新图确认', tuple(evidence), {'page': target})
            if self.port.queue_idle() is not True or frame.kind in ('battle', 'exploration'):
                return Result('blocked', '本轮队列仍在运行，未进行页面操作', tuple(evidence), {'before_action': attempt == 0})
            options = [t for t in self.transitions if t.source == frame.kind and t.precondition(frame)]
            if len(options) != 1 or attempt == self.max_actions:
                return Result('blocked' if attempt == 0 else 'partial', '没有唯一已验证页面转移，已留图', tuple(evidence),
                              {'page': frame.kind, 'before_action': attempt == 0})
            chosen = options[0]
            signature = (frame.kind, chosen.target, tuple(sorted(frame.positions.items())))
            if signature in seen:
                return Result('partial', '页面未产生预期变化，停止重复点击', tuple(evidence), {'page': frame.kind})
            seen.add(signature)
            # Recheck ownership immediately before input, not only at entry.
            if self.port.queue_idle() is not True or self.port.owns_control() is not True:
                return Result('blocked' if attempt == 0 else 'partial', '控制权已变化，未追加操作', tuple(evidence),
                              {'before_action': attempt == 0})
            chosen.action(self.port, frame)
            self.port.wait(1)
            after, paths = self.read('module_after')
            evidence.extend(paths)
            if after.kind != chosen.target:
                return Result('partial', '点击后的页面不符预期，未继续盲点', tuple(evidence), {'page': after.kind})
            if after.kind == target:
                return Result('succeeded', '页面转移前后均已核验', tuple(evidence), {'page': target})
        raise AssertionError('bounded loop')


def classify_existing(items):
    """Reuse accepted home/medal/quick-nav recognizers, not a second template."""
    from daily_medal_home_recovery_v1 import is_home, medal_page
    from daily_fast_proxy_yw_v1 import page_kind
    if is_home(items): return 'home', {}
    medal = medal_page(items)
    if medal: return medal, {}
    kind, point = page_kind(items)
    if kind == 'quick_nav': return kind, {'home': tuple(point)}
    if kind in ('yw_map', 'yw_detail'): return kind, {}
    from activity_room_navigation_v1 import actual_room
    names = {str(t).strip() for t, x, y in items}
    # Real exit-tail failure, Oct13: Recruit times=0 ends on this normal
    # overview. Header + repeated slot labels + slot actions identify it;
    # the word 公开招募 alone also exists on home/quick-nav, so is insufficient.
    normalized = [(''.join(str(t).split()), x, y) for t,x,y in items]
    if (any(t == '公开招募' and x < 800 and y < 300 for t,x,y in normalized)
            and sum('职位需求' in t and y >= 250 for t,x,y in normalized) >= 2
            and any(t in ('立即招募', '聘用候选人', '开始招募') and y >= 250 for t,x,y in normalized)):
        return 'recruit_overview', {}
    if actual_room(items) and {'设施信息', '使用者', '装扮模式', '装扮商店'} <= names:
        return 'activity_room', {}
    from yw_lobby_route_v1 import is_lobby
    if is_lobby(items): return 'yw_lobby', {}
    if ('打捞方案' in names and any(str(t).startswith('通关') for t,x,y in items)
            and any('YW-' in str(t) for t,x,y in items)):
        return 'yw_tasks', {}
    text = ''.join(str(t) for t, x, y in items).strip()
    if not text or (len(items) <= 2 and 'RHODESISLAND' in text.upper().replace(' ', '')):
        return 'transition', {}
    # Unknown is intentional; text such as "继续" alone never creates a click.
    return 'unknown', {}


def existing_home_transitions():
    # This exact top-house control was accepted on all three medal pages.
    return tuple(Transition(source, 'quick_nav', lambda port, frame: port.tap(400, 55))
                 for source in ('medal_archive', 'medal_list', 'medal_detail',
                                'activity_room', 'yw_map', 'yw_detail', 'yw_lobby', 'yw_tasks',
                                'recruit_overview')) + (
        Transition('quick_nav', 'home', lambda port, frame: port.tap(*frame.positions['home']),
                   lambda frame: 'home' in frame.positions),)


class RuntimeVisionPort:
    def __init__(self, runtime, owns_control):
        self.runtime, self.owns_control = runtime, owns_control
    def now(self): return datetime.now(timezone.utc)
    def capture(self, tag):
        # Do not change an in-flight runtime backend from a second controller.
        if getattr(self.runtime, 'SCRIPT_SCREENSHOT_BACKEND', None) != 'adb':
            raise ValueError('shared vision requires preselected non-pausing adb capture')
        return self.runtime.shot(tag), self.now()
    def ocr(self, path): return self.runtime.ocr(path)
    def wait(self, seconds): self.runtime.wait(seconds)
    def tap(self, x, y): self.runtime.tap(x, y)
    def queue_idle(self): return self.runtime._maa_task_queue_running() is False
