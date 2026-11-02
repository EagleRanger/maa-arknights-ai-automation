"""UI update taxonomy shared by daily startup and the AI repair lane."""
import re
from daily_client_update_gate_v1 import update_required


def judge(items):
    t=''.join(''.join(str(t).split()) for t,x,y in items)
    if update_required(items):
        return dict(kind='client_package_update',action='same_channel_signed_update',
                    package='com.hypergryph.arknights.bilibili',preserve_data=True)
    if any(s in t for s in ('资源载入异常','下载失败','网络连接失败','更新失败')):
        return dict(kind='resource_update_error',action='bounded_retry_then_ai')
    if any(s in t for s in ('正在下载资源','资源下载中','正在更新资源','正在解压资源','正在校验资源')):
        match=re.search(r'(?<!\d)(\d{1,3}(?:\.\d+)?)%',t)
        value=float(match[1]) if match and float(match[1])<=100 else None
        return dict(kind='resource_update_progress',action='wait_while_progressing',percent=value)
    if '资源' in t and '下载' in t and any(s in t for s in ('是否','需要','确认')):
        return dict(kind='resource_download_prompt',action='verify_visible_confirmation')
    return dict(kind='not_update',action='normal_startup')
