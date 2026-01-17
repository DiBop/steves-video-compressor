# Steve's Video Compressor

A Docker-based GUI application for compressing video files for various platforms (Discord, YouTube, Facebook, etc.)

## Quick Start

```bash
./video-compressor.sh
```

Or launch from the application menu: **Steve's Video Compressor**

## Features

- **Drag & Drop** - Drop multiple video files onto the window
- **Preset Profiles** - One-click settings for Discord (8MB), YouTube, Facebook, WhatsApp, Text/MMS, etc.
- **Target File Size** - Specify exact output size in MB
- **GPU Detection** - Auto-detects NVENC (NVIDIA), AMF (AMD), QSV (Intel)
- **Resolution Scaling** - 4K, 1080p, 720p, 480p, or custom
- **Audio Options** - Re-encode, copy, or remove audio
- **Progress Tracking** - Real-time progress bar
- **Completion Chime** - Audio notification when done
- **View Logs** - Built-in log viewer for debugging

## Presets Available

| Preset | Target Size | Resolution |
|--------|-------------|------------|
| Discord (8MB) | 8 MB | 720p |
| Discord Nitro (50MB) | 50 MB | 1080p |
| Discord Nitro (100MB) | 100 MB | 1080p |
| WhatsApp (16MB) | 16 MB | 720p |
| Email (25MB) | 25 MB | 720p |
| Text/MMS (1MB) | 1 MB | 480p |
| Text/MMS (3MB) | 3 MB | 480p |
| Facebook (1080p) | CRF 23 | 1080p |
| Facebook (720p) | CRF 23 | 720p |
| YouTube (1080p) | CRF 18 | 1080p |
| YouTube (4K) | CRF 18 | 4K |
| Twitter/X (512MB) | 500 MB | 1080p |
| Small File (H.265) | CRF 28 | 720p |
| High Quality | CRF 18 | Original |

## Files

- `video_compressor_gui.py` - Main Python/tkinter application
- `Dockerfile` - Container definition with FFmpeg, tkinter, tkinterdnd2
- `video-compressor.sh` - Launch script
- `video-compressor.desktop` - Desktop shortcut
- `video-compressor-icon.svg` - Custom vise icon

## Commands

```bash
# Start
./video-compressor.sh

# Stop
docker stop video-compressor

# View logs
docker exec video-compressor cat /app/video_compressor.log

# Rebuild after changes
docker build -t video-compressor .
```

## Mounted Paths

Inside the container:
- `/host_home` → Your home directory
- `/media` → External drives

## Troubleshooting

**"height not divisible by 2" error:**
Fixed - the app now auto-rounds dimensions to even numbers.

**File not found errors:**
Make sure the video is in `/host_home` or `/media` (paths mounted in container).

**No GPU acceleration:**
The container may not have access to your GPU. Software encoding (libx264/libx265) is used as fallback.

## Built With

- Python 3.11
- tkinter + tkinterdnd2
- FFmpeg
- Docker

---
*Created with Claude Code*
