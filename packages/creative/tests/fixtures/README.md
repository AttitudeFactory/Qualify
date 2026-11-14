# Test fixtures

- `DejaVuSans.ttf` — font for the text-composition tests.
- `video-portrait-2s.mp4` (≈5 KB) and `video-portrait-65s.mp4` (≈15 KB) — tiny portrait clips
  for `test_video_still.py` and the planner's «Historia de más de 60 segundos» browser test
  (m-25026481). Generated with ffmpeg 8 (Homebrew), from this directory:

```bash
ffmpeg -y -f lavfi -i "testsrc=size=180x320:rate=12:duration=2" -c:v libx264 -preset veryslow \
  -crf 35 -pix_fmt yuv420p -movflags +faststart video-portrait-2s.mp4
ffmpeg -y -f lavfi -i "testsrc=size=90x160:rate=1:duration=65" -c:v libx264 -preset veryslow \
  -crf 40 -g 30 -pix_fmt yuv420p -movflags +faststart video-portrait-65s.mp4
```
