# NVEncC VPP Resize & Pad 参考

## 1. 管线顺序

NVEncC 的 VPP 滤镜链按固定顺序执行：**resize → pad**。`--output-res` 指定的是 pad 之后的最终尺寸，NVEncC 自动倒推 resize 目标：

```
resize_W = output_W − pad_left − pad_right
resize_H = output_H − pad_top − pad_bottom
```

## 2. 参数定义

### `--vpp-resize <algorithm>`

指定缩放算法。仅选择算法，不指定尺寸——尺寸由 `--output-res` 控制。

**CUDA 内置（无需额外 DLL）：**

| 算法 | 说明 |
|------|------|
| `bilinear` | 双线性插值，最快 |
| `nearest` | 最近邻，锯齿明显 |
| `spline16` | Spline 16-tap |
| `spline36` | Spline 36-tap，日常推荐 |
| `spline64` | Spline 64-tap |
| `lanczos2` | Lanczos 2-tap |
| `lanczos3` | Lanczos 3-tap |
| `lanczos4` | Lanczos 4-tap，最锐利 |

**NPP 加速（需 `nppi64_*.dll`，从 CUDA Toolkit 提取）：**

`npp_linear`, `cubic`, `cubic_bspline`, `cubic_catmull`, `cubic_b05c03`, `super`, `lanczos`

**AI 超分（新版 NVEncC）：**

`nvvfx-superres`, `ngx-vsr`, `libplacebo`

### `--vpp-pad <left>,<top>,<right>,<bottom>`

在画面的 left/top/right/bottom 方向加上黑边，单位像素。

### `--output-res <W>x<H>`

最终输出尺寸 = resize 目标 + pad。

## 3. 实战案例

**输入：** Big Buck Bunny, 640×360 (16:9), 10s, H.264, 5MB  
**目标：** 缩放到宽度 960，保持长宽比，pad 到高度 720

**计算：**

```
宽缩放比: 960 / 640 = 1.5x
等高:     360 × 1.5 = 540
缺高:     720 − 540 = 180px → 上下各 90px
```

**命令：**

```powershell
NVEncC64.exe `
  --avsw `
  -i "input.mp4" `
  --codec hevc `
  --qvbr 23 `
  -u quality `
  --output-res 960x720 `
  --vpp-resize spline36 `
  --vpp-pad 0,90,0,90 `
  --colorrange auto --colormatrix auto --colorprim auto --transfer auto --chromaloc auto `
  --audio-codec aac --audio-bitrate 192 `
  -f mp4 `
  -o "output.mp4"
```

**VPP 管线实际执行：**

```
resize(spline36):  640×360 → 960×540
pad:               960×540 → 960×720 (top=90, bottom=90)
```

**编码参数说明：**

| 参数 | 值 | 说明 |
|------|-----|------|
| `--avsw` | — | 软件解码，兼容性优先 |
| `--codec hevc` | — | H.265/HEVC 编码 |
| `--qvbr 23` | QVBR 23 | 质量目标模式，等同于 `--vbr 0 --vbr-quality 23` |
| `-u quality` | quality | NVENC 质量预设 (P7) |
| `--colorrange/colormatrix/colorprim/transfer/chromaloc auto` | auto | 色彩元数据自动继承源 |
| `--audio-codec aac --audio-bitrate 192` | AAC 192kbps | 音频重编码到 AAC 192k；NVEncC 的码率单位是 kbps，不带 `k` |
| `-f mp4` | MP4 | 封装格式 |

**编码结果：**

| 项目 | 值 |
|------|-----|
| 输入 | 640×360, 5MB |
| 输出 | 960×720, 1.82MB |
| 编码帧数 | 300 帧 (30fps × 10s) |
| 编码速度 | ~370 fps |
| 实际码率 | 1524 kbps |
| GPU | RTX 2070, VE 99%, 1260MHz |
