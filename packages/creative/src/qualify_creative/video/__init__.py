"""Video insumos for the template engine: normalization at upload (plan §2.4), and the
carousel's video slides fitted to the feed (§ request 2026-10-09)."""

from qualify_creative.video.business import (
    BUSINESS_MAX_SECONDS,
    BusinessVideoNormalizer,
    FfmpegBusinessVideoNormalizer,
    NormalizedBusinessVideo,
    UnreadableVideo,
)
from qualify_creative.video.cut import CutWindow, WindowUnavailable, cut_window, plan_window
from qualify_creative.video.fit import (
    FittedVideo,
    PyAvVideoFitter,
    SubtitleLayer,
    VideoFitter,
)
from qualify_creative.video.join import JoinClip, JoinedVideo, JoinError, join_clips
from qualify_creative.video.normalize import (
    FfmpegVideoNormalizer,
    NormalizedVideo,
    VideoNormalizer,
    is_video_filename,
)
from qualify_creative.video.shots import (
    DETECTOR_VERSION,
    SAMPLING_VERSION,
    NoVideoStream,
    SampledFrame,
    SamplingPlan,
    ShotSpan,
    VideoSourceError,
    detect_shots,
    sample_frames,
)

__all__ = [
    "BUSINESS_MAX_SECONDS",
    "BusinessVideoNormalizer",
    "FfmpegBusinessVideoNormalizer",
    "NormalizedBusinessVideo",
    "UnreadableVideo",
    "DETECTOR_VERSION",
    "SAMPLING_VERSION",
    "CutWindow",
    "NoVideoStream",
    "SampledFrame",
    "SamplingPlan",
    "ShotSpan",
    "VideoSourceError",
    "WindowUnavailable",
    "cut_window",
    "detect_shots",
    "plan_window",
    "sample_frames",
    "FfmpegVideoNormalizer",
    "FittedVideo",
    "JoinClip",
    "JoinError",
    "JoinedVideo",
    "NormalizedVideo",
    "PyAvVideoFitter",
    "SubtitleLayer",
    "VideoFitter",
    "VideoNormalizer",
    "is_video_filename",
    "join_clips",
]
