#!/usr/bin/env python3
"""Compress video files using FFmpeg."""

import argparse
import subprocess
import sys
from pathlib import Path


def compress_video(
    input_path: str,
    output_path: str | None = None,
    crf: int = 23,
    preset: str = "medium",
    resolution: str | None = None,
    codec: str = "libx264",
) -> bool:
    """
    Compress a video file using FFmpeg.

    Args:
        input_path: Path to input video file
        output_path: Path for output file (default: input_compressed.mp4)
        crf: Constant Rate Factor (0-51, lower = better quality, larger file)
             Recommended: 18-28. Default 23 is visually lossless for most content.
        preset: Encoding speed/compression tradeoff
                Options: ultrafast, superfast, veryfast, faster, fast,
                         medium, slow, slower, veryslow
        resolution: Target resolution (e.g., "1280x720", "1920x1080")
        codec: Video codec (libx264 for H.264, libx265 for H.265/HEVC)

    Returns:
        True if successful, False otherwise
    """
    input_file = Path(input_path)
    if not input_file.exists():
        print(f"Error: Input file '{input_path}' not found")
        return False

    if output_path is None:
        output_path = input_file.stem + "_compressed.mp4"

    cmd = [
        "ffmpeg",
        "-i", str(input_path),
        "-c:v", codec,
        "-crf", str(crf),
        "-preset", preset,
        "-c:a", "aac",
        "-b:a", "128k",
    ]

    if resolution:
        cmd.extend(["-vf", f"scale={resolution}"])

    cmd.extend(["-y", output_path])

    print(f"Compressing: {input_path}")
    print(f"Output: {output_path}")
    print(f"Settings: codec={codec}, crf={crf}, preset={preset}")
    if resolution:
        print(f"Resolution: {resolution}")
    print()

    try:
        subprocess.run(cmd, check=True)
        input_size = input_file.stat().st_size / (1024 * 1024)
        output_size = Path(output_path).stat().st_size / (1024 * 1024)
        reduction = (1 - output_size / input_size) * 100

        print(f"\nDone!")
        print(f"Input size:  {input_size:.1f} MB")
        print(f"Output size: {output_size:.1f} MB")
        print(f"Reduction:   {reduction:.1f}%")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error: FFmpeg failed with code {e.returncode}")
        return False
    except FileNotFoundError:
        print("Error: FFmpeg not found. Make sure it's installed and in PATH.")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Compress video files using FFmpeg",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s video.mp4
  %(prog)s video.mp4 -o smaller.mp4
  %(prog)s video.mp4 --crf 28 --preset fast
  %(prog)s video.mp4 --resolution 1280x720
  %(prog)s video.mp4 --codec libx265 --crf 28
        """,
    )
    parser.add_argument("input", help="Input video file")
    parser.add_argument("-o", "--output", help="Output file path")
    parser.add_argument(
        "--crf",
        type=int,
        default=23,
        help="Quality (0-51, lower=better, default: 23)",
    )
    parser.add_argument(
        "--preset",
        default="medium",
        choices=[
            "ultrafast", "superfast", "veryfast", "faster", "fast",
            "medium", "slow", "slower", "veryslow",
        ],
        help="Encoding speed preset (default: medium)",
    )
    parser.add_argument(
        "--resolution",
        help="Target resolution (e.g., 1280x720, 1920x1080)",
    )
    parser.add_argument(
        "--codec",
        default="libx264",
        choices=["libx264", "libx265"],
        help="Video codec (default: libx264)",
    )

    args = parser.parse_args()

    success = compress_video(
        input_path=args.input,
        output_path=args.output,
        crf=args.crf,
        preset=args.preset,
        resolution=args.resolution,
        codec=args.codec,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
