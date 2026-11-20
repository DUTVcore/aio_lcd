"""
AIO Lite Streamer - Main Application
Loads configuration -> Initializes selected hardware driver -> Streams video loop to AIO LCD.
"""

import os
import sys
import json
import time
import signal
import argparse
from typing import Dict, Any
import numpy as np
import cv2

from core.media_engine import MediaEngine
from drivers import get_driver


def create_default_test_video(output_path: str, width: int = 480, height: int = 480, duration_sec: int = 4, fps: int = 30):
    """Generates a stylish test animation video if no custom video is provided."""
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))

    total_frames = duration_sec * fps
    center = (width // 2, height // 2)
    radius = min(width, height) // 3

    for i in range(total_frames):
        frame = np.zeros((height, width, 3), dtype=np.uint8)

        # Draw tech ring
        angle = (i / total_frames) * 360
        color_val = int(127 + 127 * np.sin(i / 10.0))
        cv2.circle(frame, center, radius, (255, 180, 50), 3)
        cv2.circle(frame, center, radius + 20, (50, color_val, 255), 2)

        # Rotating tick marker
        rad = np.radians(angle)
        x2 = int(center[0] + radius * np.cos(rad))
        y2 = int(center[1] + radius * np.sin(rad))
        cv2.line(frame, center, (x2, y2), (0, 255, 255), 3)

        # Text HUD
        cv2.putText(frame, "AIO LITE STREAMER", (width // 2 - 130, height // 2 - 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        cv2.putText(frame, f"Frame: {i:04d}", (width // 2 - 60, height // 2 + 25),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (180, 180, 180), 1)

        out.write(frame)

    out.release()
    print(f"[Init] Created sample test pattern video: {output_path}")


def load_config(config_path: str) -> Dict[str, Any]:
    """Load configuration from JSON file."""
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Config file not found: {config_path}")

    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    parser = argparse.ArgumentParser(description="AIO Lite Streamer - Ultra-lightweight video streamer for AIO LCDs")
    parser.add_argument("-c", "--config", default="config.json", help="Path to config.json (default: config.json)")
    parser.add_argument("-v", "--video", help="Override video file path")
    parser.add_argument("-d", "--device", help="Override device driver name")
    parser.add_argument("-p", "--preview", action="store_true", help="Show live preview window on desktop")
    parser.add_argument("-s", "--sim", action="store_true", help="Force simulation mode (no physical USB write)")
    args = parser.parse_args()

    print("=" * 60)
    print("           ⚡ AIO LITE STREAMER - HARDWARE ENGINE ⚡")
    print("=" * 60)

    # 1. Load config
    config = load_config(args.config)
    device_name = args.device or config.get("device", "valkyrie_ms9132")
    media_cfg = config.get("media", {})
    driver_opts = config.get("driver_options", {})
    show_preview = args.preview or config.get("preview_window", False)

    if args.sim:
        driver_opts["simulation_mode"] = True

    video_path = args.video or media_cfg.get("file_path", "assets/sample.mp4")

    # If video doesn't exist, create an eye-catching test video
    if not os.path.exists(video_path):
        print(f"[Media] Video file '{video_path}' not found.")
        video_path = "assets/sample.mp4"
        if not os.path.exists(video_path):
            create_default_test_video(video_path, width=480, height=480)

    # 2. Instantiate Hardware Driver
    print(f"[Device] Loading driver for: '{device_name}'...")
    driver = get_driver(device_name, options=driver_opts)

    print(f"[Device] Target resolution: {driver.target_width}x{driver.target_height}")
    print(f"[Device] Color format: {driver.color_format.upper()} | Target FPS: {driver.fps}")

    # 3. Connect to hardware
    if not driver.connect():
        print("[Device] Failed to initialize hardware driver. Exiting.")
        sys.exit(1)

    # 4. Initialize Media Engine
    target_fps = media_cfg.get("target_fps", driver.fps)
    scale_mode = media_cfg.get("scale_mode", "crop")
    loop = media_cfg.get("loop", True)

    print(f"[Media] Initializing MediaEngine: {video_path}")
    print(f"[Media] Scaling Mode: {scale_mode.upper()} | Loop: {loop}")

    media_engine = MediaEngine(
        video_path=video_path,
        target_width=driver.target_width,
        target_height=driver.target_height,
        target_fps=target_fps,
        scale_mode=scale_mode,
        loop=loop,
    )

    # Handle graceful exit on Ctrl+C / SIGINT
    running = True

    def handle_sigint(signum, frame):
        nonlocal running
        print("\n[System] Stop signal received. Shutting down gracefully...")
        running = False

    signal.signal(signal.SIGINT, handle_sigint)

    # 5. Main streaming loop
    print("\n" + "-" * 60)
    print("🚀 Streaming active! Press Ctrl+C in terminal to stop.")
    if show_preview:
        print("🖥️  Preview window enabled. Press 'q' on preview window to quit.")
    print("-" * 60 + "\n")

    fps_timer = time.perf_counter()
    fps_counter = 0

    try:
        for frame, frame_idx in media_engine.stream_frames():
            if not running:
                break

            # Send image to AIO LCD driver
            driver.send_image(frame)
            fps_counter += 1

            # Optional desktop preview window
            if show_preview:
                cv2.imshow("AIO Streamer Preview", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    print("[Preview] Quit requested from preview window.")
                    break

            # Print statistics every 2 seconds
            now = time.perf_counter()
            elapsed = now - fps_timer
            if elapsed >= 2.0:
                current_fps = fps_counter / elapsed
                mb_sent = driver.bytes_sent / (1024 * 1024)
                print(f"[Stats] Frame: {frame_idx:05d} | Real FPS: {current_fps:5.1f} | Data Sent: {mb_sent:6.2f} MB")
                fps_counter = 0
                fps_timer = now

    except Exception as e:
        print(f"[Error] Streaming error occurred: {e}")

    finally:
        # Cleanup
        print("[System] Cleaning up resources...")
        media_engine.release()
        driver.disconnect()
        if show_preview:
            cv2.destroyAllWindows()
        print("[System] Done. Exited safely.")


if __name__ == "__main__":
    main()
