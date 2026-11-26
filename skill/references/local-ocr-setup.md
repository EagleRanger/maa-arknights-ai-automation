# 当前本地OCR要求

MAA内置OCR与本脚本的PP-OCRv6-small独立。新版直连入口不需要 `rapidocr-onnxruntime`，也不需要旧PP-OCRv3检测／识别模型。先合并新版调用代码，再移除旧安装要求；不要只给旧运行包卸依赖。

| 环境 | 要求 |
| --- | --- |
| 主Python | `Pillow`、`opencv-python`、`uiautomation`；完整包现有依赖按实际清单安装 |
| 独立OCR环境 | 当前配置为 `rapidocr==3.10.0`、`onnxruntime==1.31.0` |
| 模型文件 | 配置中的v6-small检测、识别权重，以及方向分类权重；按原URL／SHA校验，不另下旧V3模型 |

运行库的3.10.0不是“模型V3”。方向分类器文件名仍含v2、分发目录含v4，是上游组合的一部分，不是另一套旧识别引擎，不能只按名字删。

以完整包 `runtime/config/local_ocr_v6_small_v1.example.json` 为准建立本地配置：设置真实Python和隔离环境路径，按其中URL／SHA准备模型。不照抄发布者路径；不因MAA升级重装这套环境。

在完整包runtime目录自检：

```powershell
& $python -X utf8 -c "from local_ocr_v6_small_v2 import preflight; c=preflight(); print(c['model'])"
```

该检查不启动游戏。正常任务仍用原入口，区域裁剪和数字识别共用同一v6 worker；不再经过旧OCR包创建识别器。
