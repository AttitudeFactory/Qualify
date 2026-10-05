"""Video insumos for the template engine: normalization at upload (plan §2.4)."""

from qualify_creative.video.normalize import (
    FfmpegVideoNormalizer,
    NormalizedVideo,
    VideoNormalizer,
    is_video_filename,
)

__all__ = ["FfmpegVideoNormalizer", "NormalizedVideo", "VideoNormalizer", "is_video_filename"]
