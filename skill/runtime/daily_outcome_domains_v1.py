"""Shared incomplete-domain reasons for manifest, report and final popup."""
def incomplete_domains(summary):
    issues=[]
    scope=summary.get('daily_scope_result') or {}
    event=summary.get('event') or {}
    if event:
        rewards=event.get('task_rewards') or {}
        if rewards.get('status') not in ('completed','verified_no_claimable'):
            issues.append('活动任务领奖未核验: '+str(rewards.get('detail') or rewards.get('status') or '未检查'))
    security=summary.get('security') or {}
    audit=security.get('reward_service') or {}
    if security:
        if not audit.get('task_rewards_checked'):
            issues.append('保全周期任务奖励未核验')
        if not audit.get('region_rewards_checked'):
            issues.append('保全区域周期清理记录奖励未核验')
        if audit.get('tasks_remaining'):
            issues.append('保全周期仍有未达成任务')
        names=audit.get('record_objectives_remaining') or []
        if names:
            issues.append('保全区域尚未完成: '+', '.join(names))
        for row in security.get('pending_region_plan') or []:
            if row.get('action')=='deferred':
                reason={'formation_not_validated':'作业编队前置待验证',
                        'matching_job_missing':'缺少精确匹配的完整作业'}.get(row.get('reason'),row.get('reason'))
                issues.append(f"保全待办 {row['region']}: {reason}")
    if not issues and scope.get('complete') is False:
        issues.append('固定每日执行器仍有未完成步骤')
    return issues


def sr_task_page(items):
    """SR task lists are identifiable even if low-contrast English is missed."""
    import re
    task_rows=[(t,x,y) for t,x,y in items if x>=750 and 150<=y<=1080
               and re.search(r'通关\s*SR\s*[-－]\s*(?:EX\s*[-－]\s*)?\d+',t)]
    return len(task_rows)>=2


def scan_sr_tasks(app,summary):
    """Sweep the observed SR task list; unmet EX rows are valid task pages."""
    from sss_reward_pages_v1 import visually_still
    import re
    evidence=[]; claims=0
    def capture(tag):
        p=app.shot(tag); evidence.append(p); return p,app.ocr(p)
    def buttons(items):
        out=[]
        banner=any('已完成待领取的任务' in t for t,x,y in items)
        for t,x,y in items:
            t=re.sub(r'\s+','',t)
            if x>=900 and 100<y<1020 and (t in {'领取','领取奖励','一键领取','全部领取','领取全部'}
                or (t=='键领取' and banner and x>=1500 and 180<y<340)):
                out.append((x,y))
        return out
    def fail(reason):
        summary.update(status='unverified',detail=reason,evidence=evidence,claimed_buttons=claims)
        return False
    p,items=capture('sr_tasks_start')
    if not sr_task_page(items):
        return fail('未确认SR任务列表')
    for _ in range(10):
        app.swipe(1250,450,1250,850,800); app.wait(2)
        q,new=capture('sr_tasks_top')
        if not sr_task_page(new):
            return fail('回顶后任务页未确认')
        if visually_still(p,q,(800,230,1870,1000)):
            break
        p=q
    else:
        return fail('任务列表顶部未确认')
    stable=0
    for i in range(30):
        p,items=capture(f'sr_task_sweep_{i}')
        if not sr_task_page(items):
            return fail('任务页丢失')
        points=buttons(items)
        if points:
            app.tap(*points[0]); app.wait(2)
            reward=app._drain_reward_sequence()
            q,new=capture('sr_task_claim_verified')
            if not sr_task_page(new) or (not reward and len(buttons(new))>=len(points)):
                return fail('领取后未确认奖励页或待领按钮减少')
            claims+=1; stable=0; continue
        if any('待领取' in t for t,x,y in items):
            return fail('页面显示待领取但按钮未定位')
        app.swipe(1250,850,1250,450,800); app.wait(2)
        q,new=capture('sr_tasks_next')
        stable=stable+1 if visually_still(p,q,(800,230,1870,1000)) else 0
        if stable>=2:
            summary.update(status='completed',claimed_buttons=claims,evidence=evidence,
                           detail='任务列表从顶部到末尾已扫描；无当前可领取项，未达成任务仍保留')
            return True
    return fail('任务扫描达到上限，未宣称领取完毕')
