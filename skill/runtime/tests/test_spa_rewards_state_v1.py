from spa_rewards_state_v1 import inspect,verified_purchase,verified_claim
from unittest.mock import patch
from spa_rewards_state_v1 import observe


def shop(balance=None):
    rows=[('限时兑换',1722,56),('累计消耗认证',1056,589),('模组数据块',583,678),('剩余3',692,736),('3000',1306,611)]
    if balance is not None:rows.append((str(balance),1550,60))
    return rows


def test_new_shop_not_old_level_track_and_missing_balance_not_zero():
    s=inspect(shop())
    assert s['page']=='shop' and s['balance'] is None
    assert s['next_action']=='reread_currency_roi' and not s['all_rewards_complete']
    s=inspect(shop(0))
    assert s['next_action']=='no_exchange_affordable_now' and not s['all_rewards_complete']


def test_target_progress_is_not_a_purchase_or_all_claimed():
    s=inspect([('关键目标',977,66),('通过第3回合',779,256),('0/1',1343,230)])
    assert s['page']=='targets' and not s['visible_claim_buttons']
    assert not s['all_rewards_complete'] and s['purchases']==0


def test_purchase_requires_real_cost_and_goods_evidence():
    a,b=inspect(shop(600)),inspect(shop(300))
    assert not verified_purchase(a,b)
    assert verified_purchase(a,b,item_remaining_before=3,item_remaining_after=2)
    assert not verified_purchase(a,a,reward_reveal=True)
    assert not verified_purchase(a,inspect(shop()),reward_reveal=True)


def test_claim_requires_counter_and_reward_evidence():
    assert verified_claim(before_claimable=2,after_claimable=1,reward_reveal=True)
    assert not verified_claim(before_claimable=2,after_claimable=2,reward_reveal=True)
    assert not verified_claim(before_claimable=None,after_claimable=0,reward_reveal=True)


def test_purchase_dialog_is_not_free_reward_or_shop_balance_position():
    rows=[('售价',1277,297),('商品内容',1218,455),('购买数量',1374,557),
          ('总计支付',1315,869),('40',1820,57),('300',1454,296),('0',1376,633)]
    state=inspect(rows)
    assert state['page']=='purchase_dialog' and state['balance']==40
    assert state['next_action']=='validate_item_quantity_and_budget'
    assert not state['visible_claim_buttons'] and state['purchases']==0


def test_lobby_currency_uses_own_roi_and_does_not_mean_claimed():
    state=inspect([('功勋兑换处',217,954),('极速模拟',1335,1002),('40',174,990)])
    assert state['page']=='lobby' and state['balance']==40
    assert not state['all_rewards_complete']


def test_missing_currency_local_reread_is_bounded_and_not_a_click():
    with patch('ocr_tolerance_v1.line_items',side_effect=[[],[('40',1545,65)]]) as read:
        state=observe(None,'image.png',shop())
    assert state['balance']==40 and read.call_count==2 and state['purchases']==0
    with patch('ocr_tolerance_v1.line_items',return_value=[]) as read:
        state=observe(None,'image.png',shop())
    assert state['balance'] is None and read.call_count==2
