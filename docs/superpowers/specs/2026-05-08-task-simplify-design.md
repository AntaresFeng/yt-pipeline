# Task 简化设计

## 目标

将 dataclass Task 从 11 个字段精简到 7 个，删除只写不读的死字段。

## 简化后 Task

```python
@dataclass
class Task:
    url: str
    state: str = States.PENDING
    error: str | None = None
    video_id: str | None = None
    video_path: str | None = None
    thumbnail_path: str | None = None
    ffmpeg_command: list[str] | None = None
```

## 删除的字段

| 字段 | 原因 |
|------|------|
| `title` | 只写不读，未被序列化 |
| `credits_path` | 只写不读，`.description` 文件是 `generate_credits()` 的副作用产物，路径无需存储 |
| `strategy` | 只写不读，策略值仅在本地用于构建 ffmpeg_command |
| `output_path` | 只写不读，输出路径已嵌入 ffmpeg_command 参数中 |

`error` 保留：虽不被代码读取，但写入 progress.json 供人工排障。

## 变更清单

| 文件 | 变更 |
|------|------|
| `model.py` | 删除 4 个字段定义 |
| `persistence.py` | `_SERIALIZED_FIELDS` 删除 4 个对应项（`title` 本就不在其中） |
| `download_worker.py` | 删除 `task.title =`、`task.credits_path =`；`generate_credits()` 签名 `-> None`，调用处不再赋值 |
| `assessment_worker.py` | 删除 `task.strategy =`、`task.output_path =` |
| `tests/conftest.py` | `mock_download` 删除 `title`、`credits_path` 赋值 |
| `tests/test_pipeline.py` | progress.json 字典删除 `strategy` 字段 |

## 边界条件

- `generate_credits()` 文件落地逻辑不变，仅不再返回路径
- 序列化/反序列化不受影响——`Task(**kwargs)` 忽略未知字段，加载旧 progress.json 时多余键被忽略
- 新 progress.json 写入时不再包含已删除字段，文件体积略减小
