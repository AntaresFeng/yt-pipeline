# yt-dlp 报错重试机制分析

基于 yt-dlp 2026.3.17 源码分析。

## 核心重试基础设施

yt-dlp 使用统一的 `RetryManager` 类（`utils/_utils.py:5240`）驱动所有重试逻辑。关键条件：

```python
self._error is not NO_DEFAULT and self.attempt <= self.retries
```

即：初始尝试 + N 次重试 = N+1 次总尝试。

## 四层重试配置

| 参数 | CLI 标志 | CLI 默认值 | API 默认值 | 适用场景 |
|---|---|---|---|---|
| `retries` | `-R, --retries` | **10** | 0 | HTTP 下载 |
| `fragment_retries` | `--fragment-retries` | **10** | 0 | DASH/HLS 分片 |
| `file_access_retries` | `--file-access-retries` | **3** | 3 | 文件读写 |
| `extractor_retries` | 无 CLI 标志 | **3** | 3 | 提取器 API 请求 |

重试间隔可通过 `--retry-sleep` 配置，支持线性增长（`linear=START:END:STEP`）和指数退避（`exp=START:END:BASE`），按类型（`http`/`fragment`/`file_access`/`extractor`）独立配置。

### CLI 与 API 默认值差异的原因

CLI 通过 `optparse` 的 `default=10` 设置默认值，而 API 调用 `YoutubeDL(params={...})` 不经过 option parser。当 params 中缺少 `retries` 键时，`self.params.get('retries')` 返回 `None`，`RetryManager.__init__` 做 `_retries or 0`，结果为 0（不重试）。

`extractor_retries` 和 `file_access_retries` 不受影响，因为代码中使用 `get_param('extractor_retries', 3)` 和 `get_param('file_access_retries', 3)` 带了硬编码默认值 3。

**API 调用要与 CLI 行为一致**，需显式传入：

```python
yt_dlp.YoutubeDL({
    'retries': 10,
    'fragment_retries': 10,
    # extractor_retries 和 file_access_retries 本身默认 3，无需额外设置
})
```

## 异常类层级与重试行为

```
YoutubeDLError
├── ExtractorError（expected 属性区分是否预期内）
│   ├── UnsupportedError          → 不重试，直接退出
│   ├── RegexNotFoundError        → 不重试
│   ├── GeoRestrictedError        → 条件重试（可能 fake IP）
│   ├── UserNotLive               → 不重试
│   └──（网络异常自动标记 expected=True）
├── DownloadError                 → 不重试（内部已有自己的重试）
├── UnavailableVideoError         → 不重试
├── ContentTooShortError          → 重试（HTTP 层包装为 RetryDownload）
├── ReExtractInfo                 → 无限重试（重新提取信息）
│   └── ThrottledDownload         → 无限重试（限速触发）
├── DownloadCancelled             → 不重试
│   ├── ExistingVideoReached      → 直接退出
│   ├── RejectedVideoReached      → 直接退出
│   └── MaxDownloadsReached       → 直接退出
├── PostProcessingError           → 不重试
├── SameFileError                 → 不重试
├── CookieLoadError               → 不重试（始终 re-raise）
└── RequestError
    ├── TransportError            → 重试
    │   ├── IncompleteRead        → 重试
    │   ├── SSLError              → 重试
    │   └── ProxyError            → 重试
    └── HTTPError                 → 看状态码
        ├── 403, 429              → 不重试
        └── 其他                  → 重试
```

## 各场景重试行为详解

### 1. HTTP 下载（`downloader/http.py:360`）— 重试 10 次

三个内部控制异常管理重试流程：

- `SucceedDownload` — 下载成功，退出重试循环
- `RetryDownload` — 触发重试（包装源异常）
- `NextFragment` — 移至下一分片，不计入重试次数

| 触发异常 | 行为 |
|---|---|
| `TransportError`（网络中断） | 重试 |
| `ContentTooShortError`（下载不完整） | 重试 |
| `OSError`（文件写入失败） | **不重试**，直接返回 False |
| 限速检测 | 抛 `ThrottledDownload`，触发重新提取而非重试 |

### 2. 分片下载（`downloader/fragment.py:459`）— 重试 10 次

| 触发异常 | 行为 |
|---|---|
| `HTTPError` | 重试 |
| `IncompleteRead` | 重试 |
| `DownloadError`（已走过 HTTP 重试） | **不重试**，首个分片 fatal 直接抛出 |

首个分片始终为 fatal；非 fatal 分片在重试耗尽后可跳过。

### 3. 文件访问（`downloader/common.py:232`）— 重试 3 次

| 触发异常 | 行为 |
|---|---|
| `OSError(EACCES)` 权限拒绝 | 重试 |
| `OSError(EINVAL)` 无效参数 | 重试 |
| 其他 `OSError` | **不重试**，立即失败 |

应用于 `sanitize_open`、`try_remove`、`try_rename`。

### 4. 提取器（`extractor/youtube/_base.py:944`）— 重试 3 次

| 触发异常 | 行为 |
|---|---|
| 网络异常（非 403/429） | 重试 |
| `HTTPError 403`（禁止访问） | **不重试** |
| `HTTPError 429`（频率限制） | **不重试** |
| YouTube API 返回不完整数据 | 通过独立的 `icd_retries` 重试 3 次 |
| 非网络 `ExtractorError` | **不重试** |

YouTube 提取器 `_extract_response` 使用两个独立 `RetryManager`：

- `main_retries`：处理一般网络/HTTP 错误（排除 403/429）
- `icd_retries`：处理 YouTube API 返回的不完整数据

### 5. 顶层调度（`YoutubeDL.py`）

| 异常 | 行为 |
|---|---|
| `ReExtractInfo` | **无限重试**（重新提取，如限速/等待开播） |
| `GeoRestrictedError` | 不重试（除非 fake IP 成功） |
| `UnavailableVideoError` | 不重试 |
| `DownloadCancelled` 及子类 | 不重试，决定是否中断批处理 |
| `PostProcessingError` | 不重试 |
| 通用 `Exception` | 仅 `ignoreerrors=True` 时跳过 |
| `CookieLoadError` | 始终 re-raise，不被捕获 |

## 设计要点

1. **分层重试**：HTTP 层 10 次 → 分片层 10 次 → 提取器层 3 次，各层独立运作
2. **HTTP 403/429 是硬墙**：YouTube 提取器对这两个状态码零容忍，直接退出不重试
3. **`ReExtractInfo` 是唯一无限重试**：限速或等待开播时会反复重新提取信息
4. **`expected` 属性**：`ExtractorError` 的 `expected=True` 表示预期内的错误（网络异常自动标记），用于区分正常错误和代码 bug
5. **`network_exceptions` 哨兵元组**：`networking/exceptions.py:103` 定义为 `(HTTPError, TransportError)`，用于快速判断是否为网络错误

## 参考源码位置

| 文件 | 关键行 |
|---|---|
| `utils/_utils.py` | `RetryManager` 类（5240）、异常定义（966-1181） |
| `networking/exceptions.py` | `RequestError` 层级（11-103） |
| `downloader/http.py` | HTTP 重试循环（360-376） |
| `downloader/fragment.py` | 分片重试循环（459-470） |
| `downloader/common.py` | 文件访问重试（232-248） |
| `extractor/common.py` | 提取器重试基础设施（4066-4073） |
| `extractor/youtube/_base.py` | YouTube 特定重试逻辑（944, 1226） |
| `YoutubeDL.py` | 顶层异常处理（1693, 3639） |
