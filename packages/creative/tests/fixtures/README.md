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
- `briefs_f55f1d73/*.json` — EF-02 (ADR 50): one `ContentBrief` of each `ContentKind` (plus a
  reel replica, a part's child clip and a video by parts with its plan), serialized with
  `model_dump(mode="json")` by main `f55f1d73` BEFORE the effects recipe fields existed.
  `test_brief_fixtures_ef02.py` checks they read unchanged. Never regenerate them from a newer
  main: they are the old shape on purpose. `f55f1d73` is newer than the `9129e688` the
  EF-02 criterion names (`9129e688` is its ancestor) and is itself an ancestor of main.

- `video-rotated-90.mp4`, `video-rotated-270.mp4`, `video-rotated-45.mp4` (≈2 KB each) — phone-like
  clips for EF-01 (`test_video_upright.py`, `packages/api/tests/test_creative_clip_video_frames.py`):
  a 64×36 landscape picture stored as a phone stores it, 1 s at 10 fps, with the turn a player
  applies written in the container's display matrix (90° / 270° counter-clockwise; 45° is the
  one that must be refused as `rotation_unsupported`). Grey with a red band along the stored
  top edge and a blue one along the stored left edge, so a test checks the direction of the
  turn and not only the aspect. Generated with PyAV alone (`VideoStream.set_display_rotation`,
  no `ffmpeg` binary), from the repository root:

```bash
uv run --no-sync python packages/creative/tests/fixtures/make_rotated_fixtures.py
```
