# 安装与配置
本包面向 Windows、MuMu 和 MAA。先在目标实例中安装并登录游戏；确认游戏包名、实例地址、横屏原始截图 1920×1080。便携 MAA 放在 `runtime/.runtime_maa/MAA-App/`，程序、资源和配置要完整。主 Python 需要 Pillow、OpenCV、NumPy、psutil、uiautomation；[独立 OCR](local-ocr-setup.md)另行配置。

复制 `runtime/config/receiver_profile.example.json` 为同目录 `receiver_profile.json`，填自己的账号代号、游戏包、设备地址、MuMu 路径、解释器及使用的基建方案。自带动态生产接口读取四档 333 方案；其他布局不要照填，不支持的轮班先不启用。已有配置不要覆盖。只配置要用的[可选功能](first-run-features.md)；某项需自采小图时再按[资源表](runtime-resources.md)准备。

在 `runtime` 目录用已配置的 Python 执行：

```powershell
python ark.py init
python ark.py check --task daily --probe
```

以上不启动游戏；init 建立本机绑定，probe 会检查 MAA 资源可写性。只用单项时把 daily 换成该目标。准备好后，用[任务入口](entrypoints-v125.md)预览、运行。连错设备或截图偏移见[Windows 排查](windows-portability.md)。

已安装但 MAA 弹出更新或设置向导，见[MAA 更新](maa-update-compatibility.md)。
