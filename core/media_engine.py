"""
Media Engine for AIO Lite Streamer.
Handles video decoding, resizing, aspect-ratio cropping/letterboxing,
and precise FPS synchronization.
"""

import time
import os
from typing import Generator, Tuple, Optional
import cv2
import numpy as np


class MediaEngine:
    """
    Decodes video files, applies aspect ratio scaling (crop/fit/stretch),
    and synchronizes frame delivery to the target FPS.
    """

    def __init__(
        self,
        video_path: str,
        target_width: int,
        target_height: int,
        target_fps: Optional[int] = None,
        scale_mode: str = "crop",
        loop: bool = True,
    ):
        """
        Args:
            video_path: Path to video (mp4, mkv, avi, gif) or static image file.
            target_width: Desired width for LCD screen.
            target_height: Desired height for LCD screen.
            target_fps: Target FPS cap. If None, uses video's native FPS.
            scale_mode: 'crop' (center crop to fill, default),
                        'fit' (letterbox with black bars),
                        'stretch' (direct distortion).
            loop: Whether to loop video playback indefinitely.
        """
        self.video_path = video_path
        self.target_width = target_width
        self.target_height = target_height
        self.scale_mode = scale_mode.lower()
        self.loop = loop

        if not os.path.exists(video_path):
            raise FileNotFoundError(f"Media file not found: {video_path}")

        self.cap = cv2.VideoCapture(video_path)
        if not self.cap.isOpened():
            raise RuntimeError(f"Failed to open media source: {video_path}")

        # Extract native properties
        native_fps = self.cap.get(cv2.CAP_PROP_FPS)
        if native_fps is None or native_fps <= 0 or np.isnan(native_fps):
            native_fps = 30.0

        self.native_fps = native_fps
        self.fps = target_fps if (target_fps and target_fps > 0) else native_fps
        self.frame_interval = 1.0 / self.fps
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))

        self._is_running = False

    def _process_frame(self, frame: np.ndarray) -> np.ndarray:
        """
        Resize and crop or pad frame to match (target_width, target_height).
        """
        src_h, src_w = frame.shape[:2]
        dst_w, dst_h = self.target_width, self.target_height

        if src_w == dst_w and src_h == dst_h:
            return frame

        if self.scale_mode == "stretch":
            return cv2.resize(frame, (dst_w, dst_h), interpolation=cv2.INTER_LINEAR)

        elif self.scale_mode == "crop":
            # Center crop to fill target aspect ratio
            src_aspect = src_w / src_h
            dst_aspect = dst_w / dst_h

            if src_aspect > dst_aspect:
                # Video is wider than screen: crop left and right
                new_w = int(src_h * dst_aspect)
                offset_x = (src_w - new_w) // 2
                cropped = frame[:, offset_x : offset_x + new_w]
            else:
                # Video is taller than screen: crop top and bottom
                new_h = int(src_w / dst_aspect)
                offset_y = (src_h - new_h) // 2
                cropped = frame[offset_y : offset_y + new_h, :]

            return cv2.resize(cropped, (dst_w, dst_h), interpolation=cv2.INTER_AREA)

        elif self.scale_mode == "fit":
            # Letterbox / pillarbox with black borders
            src_aspect = src_w / src_h
            dst_aspect = dst_w / dst_h

            if src_aspect > dst_aspect:
                # Video is wider: fit to width, black bars top/bottom
                scale = dst_w / src_w
                scaled_w = dst_w
                scaled_h = int(src_h * scale)
            else:
                # Video is taller: fit to height, black bars left/right
                scale = dst_h / src_h
                scaled_h = dst_h
                scaled_w = int(src_w * scale)

            resized = cv2.resize(frame, (scaled_w, scaled_h), interpolation=cv2.INTER_AREA)
            canvas = np.zeros((dst_h, dst_w, 3), dtype=np.uint8)

            y_offset = (dst_h - scaled_h) // 2
            x_offset = (dst_w - scaled_w) // 2
            canvas[y_offset : y_offset + scaled_h, x_offset : x_offset + scaled_w] = resized
            return canvas

        else:
            # Fallback to direct resize
            return cv2.resize(frame, (dst_w, dst_h), interpolation=cv2.INTER_LINEAR)

    def stream_frames(self) -> Generator[Tuple[np.ndarray, int], None, None]:
        """
        Yields (processed_frame, frame_idx) at the target FPS.
        Handles loop and precise frame timing.
        """
        self._is_running = True
        frame_idx = 0
        next_frame_time = time.perf_counter()

        while self._is_running:
            ret, frame = self.cap.read()

            if not ret:
                if self.loop:
                    # Rewind to first frame
                    self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ret, frame = self.cap.read()
                    if not ret:
                        # Cannot read even after rewind, break
                        break
                else:
                    break

            processed = self._process_frame(frame)
            yield processed, frame_idx
            frame_idx += 1

            # Precision FPS sleep synchronization
            next_frame_time += self.frame_interval
            sleep_duration = next_frame_time - time.perf_counter()

            if sleep_duration > 0.001:
                time.sleep(sleep_duration)
            elif sleep_duration < -self.frame_interval:
                # Fell behind more than 1 frame, reset reference clock
                next_frame_time = time.perf_counter()

    def stop(self) -> None:
        """Stop the streaming generator."""
        self._is_running = False

    def release(self) -> None:
        """Release video capture resources."""
        self.stop()
        if self.cap and self.cap.isOpened():
            self.cap.release()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.release()
