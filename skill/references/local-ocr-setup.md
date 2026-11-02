# 本地 OCR：模型来源、固定版本、配置与自检

迁移时先读本页，再配置 `runtime/config/local_ocr_v6_small_v1.json`。本页只处理本项目独立 OCR worker，不修改 MAA 内置 OCR，也不代替游戏任务授权。下述安装命令供接收方获准配置本机后执行；本次说明修订没有执行安装或下载模型。

## 这份 ONNX 从哪里来

本配置使用 **RapidAI/RapidOCR 在 ModelScope 的 `v3.10.0` ONNX 分发**，不是 `.rten`，也不是其他平台另一份同名或 `inference.onnx` 导出。不同格式、导出参数或分发文件的 SHA-256 可以不同；不要改扩展名、随意转换模型或用新下载文件的哈希覆盖预期值。

来源依据为 RapidAI 上游 [`python/rapidocr/default_models.yaml`](https://github.com/RapidAI/RapidOCR/blob/80b427d69bfc5b91a12913394875910296c6f315/python/rapidocr/default_models.yaml)，固定在提交 `80b427d69bfc5b91a12913394875910296c6f315`。本次将其中 URL 和 SHA-256 与本包配置逐项对照一致，**未下载模型二进制重新验算**；接收方仍须对自己取得的文件计算 SHA-256。

版本含义分开：

- `PP-OCRv6-small`：检测/识别模型代数与规模，不是运行库主版本。
- `rapidocr==3.10.0`：独立 worker 的 Python 库；配置字段为 `library`。
- `onnxruntime==1.31.0`：推理运行库；配置字段为 `onnxruntime`。
- 下载路径中的 `resolve/v3.10.0`：ModelScope 分发修订号。不要自行改成 `master`、`latest` 或另一个版本。
- `rapidocr-onnxruntime`：业务层保留的旧接口包，与上述 `rapidocr` 不同；不能只装其中一个就认定两层环境均已满足。

## 文件、地址与落盘位置

以解压后的 `skill/runtime/` 为根，保留以下文件名。每项完整下载 URL 和预期 SHA-256 以 [`local_ocr_v6_small_v1.example.json`](../runtime/config/local_ocr_v6_small_v1.example.json) 的 `models` 为准：

| 配置键 | 文件名 | 相对 runtime 的安装路径 |
| --- | --- | --- |
| `Det` | `PP-OCRv6_det_small.onnx` | `.runtime/ocr-benchmark-models/PP-OCRv6_det_small.onnx` |
| `Rec` | `PP-OCRv6_rec_small.onnx` | `.runtime/ocr-benchmark-models/PP-OCRv6_rec_small.onnx` |
| `Cls` | `ch_ppocr_mobile_v2.0_cls_mobile.onnx` | `.runtime/ocr-benchmark-models/ch_ppocr_mobile_v2.0_cls_mobile.onnx` |

`Det`、`Rec` 是 PP-OCRv6 small；`Cls` 刻意沿用上游 PP-OCRv4 分发目录中的 v2.0 方向分类模型，不要为了名称统一替换它。现有 `preflight()` 会校验三项，即使某次识别未启用分类，也不能漏放 `Cls`。

`model_distribution`、`download_url`、`configuration_guide` 和 `library_name` 是说明性元数据；现有运行器不会因这些字段自动联网下载。

## 配置隔离环境与真实解释器

worker 当前按 Windows 的 `Lib/site-packages` 布局取依赖，源环境基线为 Python 3.13 x64。用接收方真实安装、版本和位数相同的解释器创建隔离环境，避免混用其他 Python 的原生扩展。若固定依赖在目标 Python 上没有可用构建，先报告兼容性缺口，不静默改用最新版。

以下在仓库根执行。`$basePython` 必须替换成接收方已核验的真实 Python 可执行文件，不能用 WindowsApps 占位程序，也不能直接填虚拟环境的 launcher。已有虚拟环境时，可用其 Python 执行 `import sys; print(sys._base_executable)` 查到基础解释器，再核验该路径确实存在。

```powershell
$runtimeRoot = (Resolve-Path -LiteralPath '.\skill\runtime').Path
$basePython = 'REPLACE_WITH_REAL_PYTHON_EXECUTABLE'
if (-not (Test-Path -LiteralPath $basePython -PathType Leaf)) {
    throw '请先填写接收方真实 Python 路径'
}
& $basePython -c "import sys, struct; print(sys.executable, sys.version, struct.calcsize('P') * 8)"
# 新环境才创建；已有环境先核对，不覆盖其中的用户配置。
$ocrEnvironment = Join-Path $runtimeRoot '.runtime/ocr-v6-small'
if (-not (Test-Path -LiteralPath $ocrEnvironment)) {
    & $basePython -m venv $ocrEnvironment
    if ($LASTEXITCODE -ne 0) { throw 'OCR 隔离环境创建失败' }
}
$ocrPython = Join-Path $ocrEnvironment 'Scripts/python.exe'
& $ocrPython -m pip install 'rapidocr==3.10.0' 'onnxruntime==1.31.0'
if ($LASTEXITCODE -ne 0) { throw '固定 OCR 依赖安装失败；不要自动改版' }
```

复制示例为 `runtime/config/local_ocr_v6_small_v1.json`，填写 `base_python`，保持 `environment` 为 `.runtime/ocr-v6-small`（或接收方实际的相对隔离目录）。模型路径必须位于 `runtime/` 内，不写入作者电脑目录；原有线程数、模型名、版本、哈希及超时保护保持不变。生成配置使用 UTF-8 **无 BOM**，因为运行器按 `encoding='utf-8'` 读取。

```powershell
$examplePath = Join-Path $runtimeRoot 'config/local_ocr_v6_small_v1.example.json'
$configPath = Join-Path $runtimeRoot 'config/local_ocr_v6_small_v1.json'
if (Test-Path -LiteralPath $configPath) {
    throw '已有活动 OCR 配置：先核对差异，不自动覆盖'
}
$ocrConfig = Get-Content -LiteralPath $examplePath -Raw -Encoding UTF8 | ConvertFrom-Json
$ocrConfig.base_python = $basePython
[IO.File]::WriteAllText($configPath, ($ocrConfig | ConvertTo-Json -Depth 12), [Text.UTF8Encoding]::new($false))
```

## 取得缺失模型并校验

接收方需要下载时，按配置中的固定 URL 获取缺失文件。已存在的文件先算哈希，不为修复错误盲目覆盖；不一致就停止并检查来源、是否误拿其他导出、下载是否为 HTML/错误页或是否损坏。`.rten` 改名为 `.onnx` 不能解决不匹配。

```powershell
foreach ($taskName in @('Det', 'Rec', 'Cls')) {
    $model = $ocrConfig.models.$taskName
    $modelFile = Join-Path $runtimeRoot $model.path
    if (-not (Test-Path -LiteralPath $modelFile)) {
        New-Item -ItemType Directory -Path (Split-Path -Parent $modelFile) -Force | Out-Null
        Invoke-WebRequest -Uri $model.download_url -OutFile $modelFile -TimeoutSec 180
    }
    $actualHash = (Get-FileHash -LiteralPath $modelFile -Algorithm SHA256).Hash
    if ($actualHash -cne $model.sha256) {
        throw ('OCR 模型哈希不一致，禁止启动：' + $taskName)
    }
}
```

## 使用现有自检，不用游戏验证安装

完成配置后，先调用已有只读预检。它检查模型名、线程数、三个文件的路径与 SHA、基础解释器、隔离依赖及固定版本，不启动 OCR worker、MAA、模拟器或游戏：

```powershell
Push-Location -LiteralPath $runtimeRoot
try {
    & $basePython -X utf8 -c "import local_ocr_v6_small_v1 as o; c=o.preflight(); print('OCR_PREFLIGHT_OK', c['model'], c['library'], c['onnxruntime'])"
    if ($LASTEXITCODE -ne 0) { throw 'OCR 预检失败；先处理错误，不进入游戏' }
} finally {
    Pop-Location
}
```

需要进一步核验推理且接收方已允许时，先创建 `runtime/outputs/` 父目录，再通过现有 `Worker.start()` / `Worker.request('scan', path=..., use_det=True, use_cls=False)` 对一张接收方自备、无敏感内容的静态图片检查，最后在 `finally` 中调用 `Worker.close()`。该步骤会启动隔离 OCR 子进程并写本地日志，但不会自动进行游戏操作；本次说明修订未执行这一推理检查。

预检通过只证明本机配置门通过，静态图片识别也不等于游戏、ROI 或整套任务已通过。保留模型与依赖版本校验、单控制者和原有资源/任务授权边界；不删校验、不靠自动下载或一次战斗掩盖配置问题。
