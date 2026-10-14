"""Video insumos for the template engine: normalization at upload (plan §2.4), and the
carousel's video slides fitted to the feed (§ request 2026-10-09)."""

from qualify_creative.video.fit import FittedVideo, PyAvVideoFitter, VideoFitter
from qualify_creative.video.normalize import (
    FfmpegVideoNormalizer,
    NormalizedVideo,
    VideoNormalizer,
    is_video_filename,
)

__all__ = [
    "FfmpegVideoNormalizer",
    "FittedVideo",
    "NormalizedVideo",
    "PyAvVideoFitter",
    "VideoFitter",
    "VideoNormalizer",
    "is_video_filename",
]
