#!/usr/bin/env python3
"""Video Compressor GUI with hardware acceleration support."""

import json
import logging
import os
import re
import subprocess
import sys
import threading
import tkinter as tk
import traceback
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

# Setup logging to file
LOG_FILE = Path("/app/video_compressor.log") if Path("/app").exists() else Path("video_compressor.log")
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, mode='w'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)
logger.info(f"Starting Video Compressor GUI - Log file: {LOG_FILE}")

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
    logger.info("tkinterdnd2 loaded successfully")
except ImportError as e:
    HAS_DND = False
    logger.warning(f"tkinterdnd2 not available: {e}")


@dataclass
class EncoderInfo:
    """Information about an available encoder."""
    name: str
    display_name: str
    codec: str  # h264 or h265
    is_hardware: bool
    quality_param: str  # crf, cq, or global_quality
    quality_range: tuple[int, int]
    presets: list[str]


class HardwareDetector:
    """Detect available hardware encoders."""

    ENCODERS = {
        # NVIDIA NVENC
        "h264_nvenc": EncoderInfo(
            "h264_nvenc", "NVIDIA NVENC (H.264)", "h264", True,
            "cq", (0, 51), ["p1", "p2", "p3", "p4", "p5", "p6", "p7"]
        ),
        "hevc_nvenc": EncoderInfo(
            "hevc_nvenc", "NVIDIA NVENC (H.265)", "h265", True,
            "cq", (0, 51), ["p1", "p2", "p3", "p4", "p5", "p6", "p7"]
        ),
        # AMD AMF
        "h264_amf": EncoderInfo(
            "h264_amf", "AMD AMF (H.264)", "h264", True,
            "qp_i", (0, 51), ["speed", "balanced", "quality"]
        ),
        "hevc_amf": EncoderInfo(
            "hevc_amf", "AMD AMF (H.265)", "h265", True,
            "qp_i", (0, 51), ["speed", "balanced", "quality"]
        ),
        # Intel QuickSync
        "h264_qsv": EncoderInfo(
            "h264_qsv", "Intel QuickSync (H.264)", "h264", True,
            "global_quality", (1, 51), ["veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"]
        ),
        "hevc_qsv": EncoderInfo(
            "hevc_qsv", "Intel QuickSync (H.265)", "h265", True,
            "global_quality", (1, 51), ["veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"]
        ),
        # Software (always available)
        "libx264": EncoderInfo(
            "libx264", "Software (H.264)", "h264", False,
            "crf", (0, 51), ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"]
        ),
        "libx265": EncoderInfo(
            "libx265", "Software (H.265)", "h265", False,
            "crf", (0, 51), ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"]
        ),
    }

    @staticmethod
    def get_available_encoders() -> dict[str, EncoderInfo]:
        """Detect which encoders are available on the system."""
        logger.info("Detecting available encoders...")
        available = {}

        try:
            result = subprocess.run(
                ["ffmpeg", "-encoders", "-hide_banner"],
                capture_output=True, text=True, timeout=10
            )
            output = result.stdout
            logger.debug(f"FFmpeg encoders query successful")
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.warning(f"FFmpeg query failed: {e}, falling back to software encoders")
            return {
                "libx264": HardwareDetector.ENCODERS["libx264"],
                "libx265": HardwareDetector.ENCODERS["libx265"],
            }

        for name, info in HardwareDetector.ENCODERS.items():
            if name in output:
                if info.is_hardware:
                    logger.debug(f"Testing hardware encoder: {name}")
                    if HardwareDetector._test_encoder(name):
                        available[name] = info
                        logger.info(f"Hardware encoder available: {name}")
                    else:
                        logger.debug(f"Hardware encoder not working: {name}")
                else:
                    available[name] = info
                    logger.info(f"Software encoder available: {name}")

        logger.info(f"Total encoders found: {len(available)}")
        return available

    @staticmethod
    def _test_encoder(encoder: str) -> bool:
        """Test if a hardware encoder actually works."""
        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-f", "lavfi",
                    "-i", "nullsrc=s=256x256:d=1",
                    "-c:v", encoder, "-f", "null", "-"
                ],
                capture_output=True, timeout=10
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False


class VideoCompressorGUI:
    """Main GUI application for video compression."""

    RESOLUTIONS = {
        "Keep Original": None,
        "4K (2160p)": "3840x2160",
        "1440p": "2560x1440",
        "1080p": "1920x1080",
        "720p": "1280x720",
        "480p": "854x480",
        "Custom": "custom",
    }

    AUDIO_BITRATES = ["64k", "96k", "128k", "192k", "256k", "320k"]
    FRAME_RATES = ["Keep Original", "24", "30", "60"]
    CONTAINERS = [".mp4", ".mkv", ".webm"]

    # Preset profiles: name -> settings dict
    PRESETS = {
        "Custom": None,  # Manual settings
        "Discord (8MB)": {
            "quality_mode": "filesize",
            "target_size": "8",
            "resolution": "720p",
            "audio_bitrate": "96k",
            "codec": "h264",
        },
        "Discord Nitro (50MB)": {
            "quality_mode": "filesize",
            "target_size": "50",
            "resolution": "1080p",
            "audio_bitrate": "128k",
            "codec": "h264",
        },
        "Discord Nitro (100MB)": {
            "quality_mode": "filesize",
            "target_size": "100",
            "resolution": "1080p",
            "audio_bitrate": "128k",
            "codec": "h264",
        },
        "WhatsApp (16MB)": {
            "quality_mode": "filesize",
            "target_size": "16",
            "resolution": "720p",
            "audio_bitrate": "96k",
            "codec": "h264",
        },
        "Email (25MB)": {
            "quality_mode": "filesize",
            "target_size": "25",
            "resolution": "720p",
            "audio_bitrate": "128k",
            "codec": "h264",
        },
        "Text/MMS (1MB)": {
            "quality_mode": "filesize",
            "target_size": "1",
            "resolution": "480p",
            "audio_bitrate": "64k",
            "codec": "h264",
        },
        "Text/MMS (3MB)": {
            "quality_mode": "filesize",
            "target_size": "3",
            "resolution": "480p",
            "audio_bitrate": "64k",
            "codec": "h264",
        },
        "Facebook (1080p)": {
            "quality_mode": "crf",
            "crf": 23,
            "resolution": "1080p",
            "audio_bitrate": "128k",
            "codec": "h264",
        },
        "Facebook (720p)": {
            "quality_mode": "crf",
            "crf": 23,
            "resolution": "720p",
            "audio_bitrate": "128k",
            "codec": "h264",
        },
        "YouTube (1080p)": {
            "quality_mode": "crf",
            "crf": 18,
            "resolution": "1080p",
            "audio_bitrate": "192k",
            "codec": "h264",
        },
        "YouTube (4K)": {
            "quality_mode": "crf",
            "crf": 18,
            "resolution": "4K (2160p)",
            "audio_bitrate": "256k",
            "codec": "h264",
        },
        "Telegram (2GB)": {
            "quality_mode": "crf",
            "crf": 23,
            "resolution": "Keep Original",
            "audio_bitrate": "128k",
            "codec": "h265",
        },
        "Twitter/X (512MB)": {
            "quality_mode": "filesize",
            "target_size": "500",
            "resolution": "1080p",
            "audio_bitrate": "192k",
            "codec": "h264",
        },
        "Small File (H.265)": {
            "quality_mode": "crf",
            "crf": 28,
            "resolution": "720p",
            "audio_bitrate": "96k",
            "codec": "h265",
        },
        "High Quality": {
            "quality_mode": "crf",
            "crf": 18,
            "resolution": "Keep Original",
            "audio_bitrate": "192k",
            "codec": "h264",
        },
    }

    def __init__(self, root: tk.Tk):
        logger.info("Initializing VideoCompressorGUI")
        self.root = root
        self.root.title("Steve's Video Compressor")
        self.root.geometry("700x800")
        self.root.minsize(600, 750)

        # Detect available encoders
        logger.info("Detecting encoders...")
        self.available_encoders = HardwareDetector.get_available_encoders()
        logger.info(f"Found {len(self.available_encoders)} encoders")

        # State variables
        self.input_files: list[Path] = []
        self.is_compressing = False
        self.cancel_requested = False
        self.current_process: subprocess.Popen | None = None

        logger.info("Creating widgets...")
        self._create_widgets()
        logger.info("Updating encoder options...")
        self._update_encoder_options()
        logger.info("Setting up drag and drop...")
        self._setup_drag_and_drop()
        logger.info("GUI initialization complete")

    def _create_widgets(self):
        """Create all GUI widgets."""
        # Create outer frame for canvas and scrollbar
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        # Canvas for scrolling
        self.canvas = tk.Canvas(self.root, highlightthickness=0)
        self.canvas.grid(row=0, column=0, sticky="nsew")

        # Scrollbar
        scrollbar = ttk.Scrollbar(self.root, orient="vertical", command=self.canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        # Main frame inside canvas
        main_frame = ttk.Frame(self.canvas, padding="10")
        self.canvas_window = self.canvas.create_window((0, 0), window=main_frame, anchor="nw")

        # Configure canvas scrolling
        def _configure_scroll(event):
            self.canvas.configure(scrollregion=self.canvas.bbox("all"))

        def _configure_canvas_width(event):
            self.canvas.itemconfig(self.canvas_window, width=event.width)

        main_frame.bind("<Configure>", _configure_scroll)
        self.canvas.bind("<Configure>", _configure_canvas_width)

        # Mouse wheel scrolling
        def _on_mousewheel(event):
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _on_mousewheel_linux(event):
            if event.num == 4:
                self.canvas.yview_scroll(-1, "units")
            elif event.num == 5:
                self.canvas.yview_scroll(1, "units")

        self.canvas.bind_all("<MouseWheel>", _on_mousewheel)
        self.canvas.bind_all("<Button-4>", _on_mousewheel_linux)
        self.canvas.bind_all("<Button-5>", _on_mousewheel_linux)

        main_frame.columnconfigure(0, weight=1)

        row = 0

        # === Drop Zone ===
        self.drop_frame = tk.Frame(main_frame, bg="#e8e8e8", highlightbackground="#aaaaaa", highlightthickness=2)
        self.drop_frame.grid(row=row, column=0, sticky="ew", pady=(0, 10), ipady=20)
        row += 1

        self.drop_label = tk.Label(
            self.drop_frame,
            text="Drop video files here\nor click Browse",
            bg="#e8e8e8",
            fg="#666666",
            font=("TkDefaultFont", 11),
            cursor="hand2"
        )
        self.drop_label.pack(expand=True, fill="both", pady=10)
        self.drop_label.bind("<Button-1>", lambda e: self._browse_input())

        # === Preset Profile Section ===
        preset_frame = ttk.LabelFrame(main_frame, text="Quick Preset", padding="10")
        preset_frame.grid(row=row, column=0, sticky="ew", pady=(0, 10))
        preset_frame.columnconfigure(1, weight=1)
        row += 1

        ttk.Label(preset_frame, text="Preset:").grid(row=0, column=0, sticky="w")
        self.preset_profile_var = tk.StringVar(value="Custom")
        self.preset_profile_combo = ttk.Combobox(
            preset_frame,
            textvariable=self.preset_profile_var,
            values=list(self.PRESETS.keys()),
            state="readonly",
            width=25
        )
        self.preset_profile_combo.grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.preset_profile_combo.bind("<<ComboboxSelected>>", self._apply_preset)

        self.preset_description = ttk.Label(preset_frame, text="Manual settings", foreground="gray")
        self.preset_description.grid(row=0, column=2, sticky="w", padx=(15, 0))

        # === Input/Output Section ===
        io_frame = ttk.LabelFrame(main_frame, text="Input / Output", padding="10")
        io_frame.grid(row=row, column=0, sticky="ew", pady=(0, 10))
        io_frame.columnconfigure(1, weight=1)
        row += 1

        ttk.Label(io_frame, text="Input Files:").grid(row=0, column=0, sticky="w")
        self.input_label = ttk.Label(io_frame, text="No files selected", foreground="gray")
        self.input_label.grid(row=0, column=1, sticky="w", padx=(10, 0))

        btn_frame = ttk.Frame(io_frame)
        btn_frame.grid(row=0, column=2, padx=(10, 0))
        ttk.Button(btn_frame, text="Browse", command=self._browse_input).pack(side="left")
        ttk.Button(btn_frame, text="Clear", command=self._clear_input).pack(side="left", padx=(5, 0))

        ttk.Label(io_frame, text="Output Folder:").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.output_var = tk.StringVar(value="Same as input")
        self.output_entry = ttk.Entry(io_frame, textvariable=self.output_var)
        self.output_entry.grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=(10, 0))
        ttk.Button(io_frame, text="Browse", command=self._browse_output).grid(row=1, column=2, padx=(10, 0), pady=(10, 0))

        ttk.Label(io_frame, text="Filename Suffix:").grid(row=2, column=0, sticky="w", pady=(10, 0))
        self.suffix_var = tk.StringVar(value="_compressed")
        ttk.Entry(io_frame, textvariable=self.suffix_var, width=20).grid(row=2, column=1, sticky="w", padx=(10, 0), pady=(10, 0))

        ttk.Label(io_frame, text="Container:").grid(row=3, column=0, sticky="w", pady=(10, 0))
        self.container_var = tk.StringVar(value=".mp4")
        ttk.Combobox(io_frame, textvariable=self.container_var, values=self.CONTAINERS, state="readonly", width=10).grid(row=3, column=1, sticky="w", padx=(10, 0), pady=(10, 0))

        # === Encoder Section ===
        encoder_frame = ttk.LabelFrame(main_frame, text="Encoder / GPU", padding="10")
        encoder_frame.grid(row=row, column=0, sticky="ew", pady=(0, 10))
        encoder_frame.columnconfigure(1, weight=1)
        row += 1

        ttk.Label(encoder_frame, text="Codec:").grid(row=0, column=0, sticky="w")
        self.codec_var = tk.StringVar(value="h264")
        codec_frame = ttk.Frame(encoder_frame)
        codec_frame.grid(row=0, column=1, sticky="w", padx=(10, 0))
        ttk.Radiobutton(codec_frame, text="H.264", variable=self.codec_var, value="h264", command=self._update_encoder_options).pack(side="left")
        ttk.Radiobutton(codec_frame, text="H.265 (HEVC)", variable=self.codec_var, value="h265", command=self._update_encoder_options).pack(side="left", padx=(20, 0))

        ttk.Label(encoder_frame, text="Encoder:").grid(row=1, column=0, sticky="w", pady=(10, 0))
        self.encoder_var = tk.StringVar()
        self.encoder_combo = ttk.Combobox(encoder_frame, textvariable=self.encoder_var, state="readonly", width=30)
        self.encoder_combo.grid(row=1, column=1, sticky="w", padx=(10, 0), pady=(10, 0))
        self.encoder_combo.bind("<<ComboboxSelected>>", self._on_encoder_changed)

        # === Video Quality Section ===
        quality_frame = ttk.LabelFrame(main_frame, text="Video Quality", padding="10")
        quality_frame.grid(row=row, column=0, sticky="ew", pady=(0, 10))
        quality_frame.columnconfigure(1, weight=1)
        row += 1

        ttk.Label(quality_frame, text="Mode:").grid(row=0, column=0, sticky="w")
        self.quality_mode_var = tk.StringVar(value="crf")
        mode_frame = ttk.Frame(quality_frame)
        mode_frame.grid(row=0, column=1, sticky="w", padx=(10, 0))
        ttk.Radiobutton(mode_frame, text="Constant Quality", variable=self.quality_mode_var, value="crf", command=self._update_quality_widgets).pack(side="left")
        ttk.Radiobutton(mode_frame, text="Target Bitrate", variable=self.quality_mode_var, value="bitrate", command=self._update_quality_widgets).pack(side="left", padx=(15, 0))
        ttk.Radiobutton(mode_frame, text="Target File Size", variable=self.quality_mode_var, value="filesize", command=self._update_quality_widgets).pack(side="left", padx=(15, 0))

        # CRF slider
        self.crf_frame = ttk.Frame(quality_frame)
        self.crf_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Label(self.crf_frame, text="Quality:").pack(side="left")
        self.crf_var = tk.IntVar(value=23)
        self.crf_scale = ttk.Scale(self.crf_frame, from_=18, to=35, variable=self.crf_var, orient="horizontal", command=self._update_crf_label)
        self.crf_scale.pack(side="left", fill="x", expand=True, padx=(10, 10))
        self.crf_label = ttk.Label(self.crf_frame, text="23 (Balanced)", width=20)
        self.crf_label.pack(side="left")

        # Bitrate input
        self.bitrate_frame = ttk.Frame(quality_frame)
        self.bitrate_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Label(self.bitrate_frame, text="Target Bitrate:").pack(side="left")
        self.bitrate_var = tk.StringVar(value="5000")
        ttk.Entry(self.bitrate_frame, textvariable=self.bitrate_var, width=10).pack(side="left", padx=(10, 0))
        ttk.Label(self.bitrate_frame, text="kbps").pack(side="left", padx=(5, 0))
        self.bitrate_frame.grid_remove()

        # Target file size input
        self.filesize_frame = ttk.Frame(quality_frame)
        self.filesize_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Label(self.filesize_frame, text="Target Size:").pack(side="left")
        self.target_size_var = tk.StringVar(value="8")
        ttk.Entry(self.filesize_frame, textvariable=self.target_size_var, width=10).pack(side="left", padx=(10, 0))
        ttk.Label(self.filesize_frame, text="MB").pack(side="left", padx=(5, 0))
        self.filesize_frame.grid_remove()

        ttk.Label(quality_frame, text="Preset:").grid(row=4, column=0, sticky="w", pady=(10, 0))
        self.preset_var = tk.StringVar()
        self.preset_combo = ttk.Combobox(quality_frame, textvariable=self.preset_var, state="readonly", width=15)
        self.preset_combo.grid(row=4, column=1, sticky="w", padx=(10, 0), pady=(10, 0))
        ttk.Label(quality_frame, text="(Slower = smaller file)", foreground="gray").grid(row=4, column=1, sticky="w", padx=(170, 0), pady=(10, 0))

        # === Resolution Section ===
        res_frame = ttk.LabelFrame(main_frame, text="Resolution", padding="10")
        res_frame.grid(row=row, column=0, sticky="ew", pady=(0, 10))
        res_frame.columnconfigure(1, weight=1)
        row += 1

        ttk.Label(res_frame, text="Resolution:").grid(row=0, column=0, sticky="w")
        self.resolution_var = tk.StringVar(value="Keep Original")
        self.resolution_combo = ttk.Combobox(res_frame, textvariable=self.resolution_var, values=list(self.RESOLUTIONS.keys()), state="readonly", width=15)
        self.resolution_combo.grid(row=0, column=1, sticky="w", padx=(10, 0))
        self.resolution_combo.bind("<<ComboboxSelected>>", self._on_resolution_changed)

        self.custom_res_frame = ttk.Frame(res_frame)
        self.custom_res_frame.grid(row=1, column=1, sticky="w", padx=(10, 0), pady=(10, 0))
        self.custom_width_var = tk.StringVar(value="1920")
        self.custom_height_var = tk.StringVar(value="1080")
        ttk.Entry(self.custom_res_frame, textvariable=self.custom_width_var, width=6).pack(side="left")
        ttk.Label(self.custom_res_frame, text=" x ").pack(side="left")
        ttk.Entry(self.custom_res_frame, textvariable=self.custom_height_var, width=6).pack(side="left")
        self.custom_res_frame.grid_remove()

        # === Frame Rate Section ===
        ttk.Label(res_frame, text="Frame Rate:").grid(row=2, column=0, sticky="w", pady=(10, 0))
        self.fps_var = tk.StringVar(value="Keep Original")
        ttk.Combobox(res_frame, textvariable=self.fps_var, values=self.FRAME_RATES, state="readonly", width=15).grid(row=2, column=1, sticky="w", padx=(10, 0), pady=(10, 0))

        # === Audio Section ===
        audio_frame = ttk.LabelFrame(main_frame, text="Audio", padding="10")
        audio_frame.grid(row=row, column=0, sticky="ew", pady=(0, 10))
        audio_frame.columnconfigure(1, weight=1)
        row += 1

        ttk.Label(audio_frame, text="Audio:").grid(row=0, column=0, sticky="w")
        self.audio_mode_var = tk.StringVar(value="reencode")
        audio_mode_frame = ttk.Frame(audio_frame)
        audio_mode_frame.grid(row=0, column=1, sticky="w", padx=(10, 0))
        ttk.Radiobutton(audio_mode_frame, text="Re-encode AAC", variable=self.audio_mode_var, value="reencode", command=self._update_audio_widgets).pack(side="left")
        ttk.Radiobutton(audio_mode_frame, text="Copy Original", variable=self.audio_mode_var, value="copy", command=self._update_audio_widgets).pack(side="left", padx=(20, 0))
        ttk.Radiobutton(audio_mode_frame, text="Remove", variable=self.audio_mode_var, value="remove", command=self._update_audio_widgets).pack(side="left", padx=(20, 0))

        self.audio_bitrate_frame = ttk.Frame(audio_frame)
        self.audio_bitrate_frame.grid(row=1, column=1, sticky="w", padx=(10, 0), pady=(10, 0))
        ttk.Label(self.audio_bitrate_frame, text="Bitrate:").pack(side="left")
        self.audio_bitrate_var = tk.StringVar(value="128k")
        ttk.Combobox(self.audio_bitrate_frame, textvariable=self.audio_bitrate_var, values=self.AUDIO_BITRATES, state="readonly", width=8).pack(side="left", padx=(10, 0))

        # === Progress Section ===
        progress_frame = ttk.LabelFrame(main_frame, text="Progress", padding="10")
        progress_frame.grid(row=row, column=0, sticky="ew", pady=(0, 10))
        progress_frame.columnconfigure(0, weight=1)
        row += 1

        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = ttk.Progressbar(progress_frame, variable=self.progress_var, maximum=100)
        self.progress_bar.grid(row=0, column=0, sticky="ew")

        self.status_var = tk.StringVar(value="Ready")
        self.status_label = ttk.Label(progress_frame, textvariable=self.status_var, foreground="gray")
        self.status_label.grid(row=1, column=0, sticky="w", pady=(5, 0))

        self.result_text = tk.Text(progress_frame, height=4, state="disabled", wrap="word")
        self.result_text.grid(row=2, column=0, sticky="ew", pady=(10, 0))

        # === Buttons ===
        button_frame = ttk.Frame(main_frame)
        button_frame.grid(row=row, column=0, sticky="ew", pady=(10, 0))
        row += 1

        self.compress_btn = ttk.Button(button_frame, text="Compress", command=self._start_compression)
        self.compress_btn.pack(side="left")

        self.cancel_btn = ttk.Button(button_frame, text="Cancel", command=self._cancel_compression, state="disabled")
        self.cancel_btn.pack(side="left", padx=(10, 0))

        self.logs_btn = ttk.Button(button_frame, text="View Logs", command=self._show_logs)
        self.logs_btn.pack(side="right")

    def _setup_drag_and_drop(self):
        """Configure drag-and-drop if available."""
        if not HAS_DND:
            self.drop_label.config(text="Drop video files here\n(install tkinterdnd2 for drag-drop)\nor click Browse")
            return

        # Register drop target on the drop frame and label
        self.drop_frame.drop_target_register(DND_FILES)
        self.drop_frame.dnd_bind("<<Drop>>", self._on_drop)
        self.drop_frame.dnd_bind("<<DragEnter>>", self._on_drag_enter)
        self.drop_frame.dnd_bind("<<DragLeave>>", self._on_drag_leave)

        self.drop_label.drop_target_register(DND_FILES)
        self.drop_label.dnd_bind("<<Drop>>", self._on_drop)
        self.drop_label.dnd_bind("<<DragEnter>>", self._on_drag_enter)
        self.drop_label.dnd_bind("<<DragLeave>>", self._on_drag_leave)

    def _on_drop(self, event):
        """Handle files dropped onto the drop zone."""
        # Parse the dropped file paths
        data = event.data
        logger.info(f"Drop event received, raw data: {data[:200]}...")  # Log first 200 chars
        files = self._parse_drop_data(data)
        logger.info(f"Parsed {len(files)} files from drop")

        # Filter for video files
        video_extensions = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".m4v", ".ts", ".mts", ".m2ts"}
        video_files = [f for f in files if Path(f).suffix.lower() in video_extensions]
        logger.info(f"Found {len(video_files)} video files after filtering")

        if video_files:
            self.input_files = [Path(f) for f in video_files]
            for f in self.input_files:
                logger.info(f"  - {f}")
            if len(self.input_files) == 1:
                self.input_label.config(text=self.input_files[0].name, foreground="black")
                self.drop_label.config(text=f"Selected: {self.input_files[0].name}")
            else:
                self.input_label.config(text=f"{len(self.input_files)} files selected", foreground="black")
                self.drop_label.config(text=f"Selected: {len(self.input_files)} video files")
        else:
            logger.warning(f"No valid video files in drop. Files found: {files}")
            messagebox.showwarning("Invalid Files", "No valid video files found in drop.")

        # Reset drop zone appearance
        self._on_drag_leave(None)

    def _parse_drop_data(self, data: str) -> list[str]:
        """Parse dropped file data which may contain multiple files."""
        files = []

        # tkinterdnd2 on Linux uses different formats
        # Format 1: {/path/with spaces/file.mp4} {/another/file.mp4}
        # Format 2: /path/no/spaces/file.mp4 /another/file.mp4
        # Format 3: file:///path/to/file.mp4

        # Remove file:// prefix if present
        data = data.replace("file://", "")

        if "{" in data:
            # Paths with spaces are wrapped in braces
            files = re.findall(r"\{([^}]+)\}", data)
            # Also get non-bracketed items (paths without spaces)
            remaining = re.sub(r"\{[^}]+\}", "", data).strip()
            if remaining:
                files.extend(remaining.split())
        else:
            # Simple space-separated paths (no spaces in filenames)
            # But also handle newline-separated
            data = data.replace("\r\n", "\n").replace("\r", "\n")
            for line in data.split("\n"):
                line = line.strip()
                if line:
                    # If no braces and spaces exist, assume it's a single path per line
                    if " " in line and not os.path.exists(line):
                        # Try splitting by space
                        files.extend(line.split())
                    else:
                        files.append(line)

        # Clean up paths
        cleaned = []
        for f in files:
            f = f.strip()
            if f:
                # URL decode if needed (e.g., %20 -> space)
                try:
                    from urllib.parse import unquote
                    f = unquote(f)
                except ImportError:
                    pass
                cleaned.append(f)

        logger.debug(f"Parsed drop data into {len(cleaned)} paths")
        return cleaned

    def _on_drag_enter(self, event):
        """Highlight drop zone when dragging over."""
        self.drop_frame.config(bg="#d0e8ff", highlightbackground="#0078d4")
        self.drop_label.config(bg="#d0e8ff", fg="#0078d4", text="Drop to add files")

    def _on_drag_leave(self, event):
        """Reset drop zone appearance."""
        self.drop_frame.config(bg="#e8e8e8", highlightbackground="#aaaaaa")
        if self.input_files:
            if len(self.input_files) == 1:
                text = f"Selected: {self.input_files[0].name}"
            else:
                text = f"Selected: {len(self.input_files)} video files"
        else:
            text = "Drop video files here\nor click Browse"
        self.drop_label.config(bg="#e8e8e8", fg="#666666", text=text)

    def _apply_preset(self, event=None):
        """Apply a preset profile's settings."""
        preset_name = self.preset_profile_var.get()
        preset = self.PRESETS.get(preset_name)

        if preset is None:
            # Custom mode - no changes
            self.preset_description.config(text="Manual settings")
            logger.info("Preset set to Custom (manual)")
            return

        logger.info(f"Applying preset: {preset_name}")

        # Apply codec
        if "codec" in preset:
            self.codec_var.set(preset["codec"])
            self._update_encoder_options()

        # Apply quality mode
        if "quality_mode" in preset:
            self.quality_mode_var.set(preset["quality_mode"])
            self._update_quality_widgets()

        # Apply CRF if specified
        if "crf" in preset:
            self.crf_var.set(preset["crf"])
            self._update_crf_label()

        # Apply target file size if specified
        if "target_size" in preset:
            self.target_size_var.set(preset["target_size"])

        # Apply resolution
        if "resolution" in preset:
            self.resolution_var.set(preset["resolution"])
            self._on_resolution_changed()

        # Apply audio bitrate
        if "audio_bitrate" in preset:
            self.audio_bitrate_var.set(preset["audio_bitrate"])

        # Update description
        desc_parts = []
        if "target_size" in preset:
            desc_parts.append(f"{preset['target_size']}MB")
        if "resolution" in preset and preset["resolution"] != "Keep Original":
            desc_parts.append(preset["resolution"])
        if "codec" in preset:
            desc_parts.append(preset["codec"].upper())
        self.preset_description.config(text=" | ".join(desc_parts) if desc_parts else "")

    def _update_encoder_options(self, event=None):
        """Update encoder dropdown based on selected codec."""
        codec = self.codec_var.get()
        matching = [(name, info) for name, info in self.available_encoders.items() if info.codec == codec]

        # Sort: hardware encoders first
        matching.sort(key=lambda x: (not x[1].is_hardware, x[0]))

        encoder_names = [info.display_name for _, info in matching]
        self.encoder_combo["values"] = encoder_names

        if encoder_names:
            self.encoder_combo.current(0)
            self._on_encoder_changed()

    def _on_encoder_changed(self, event=None):
        """Update presets when encoder changes."""
        display_name = self.encoder_var.get()
        for name, info in self.available_encoders.items():
            if info.display_name == display_name:
                self.preset_combo["values"] = info.presets
                mid_idx = len(info.presets) // 2
                self.preset_combo.current(mid_idx)
                break

    def _update_quality_widgets(self):
        """Show/hide quality widgets based on mode."""
        mode = self.quality_mode_var.get()
        self.crf_frame.grid_remove()
        self.bitrate_frame.grid_remove()
        self.filesize_frame.grid_remove()

        if mode == "crf":
            self.crf_frame.grid()
        elif mode == "bitrate":
            self.bitrate_frame.grid()
        elif mode == "filesize":
            self.filesize_frame.grid()

    def _update_crf_label(self, value=None):
        """Update CRF label with quality description."""
        crf = int(float(self.crf_var.get()))
        if crf <= 18:
            desc = "High Quality"
        elif crf <= 23:
            desc = "Balanced"
        elif crf <= 28:
            desc = "Smaller File"
        else:
            desc = "Low Quality"
        self.crf_label.config(text=f"{crf} ({desc})")

    def _update_audio_widgets(self):
        """Show/hide audio bitrate based on mode."""
        if self.audio_mode_var.get() == "reencode":
            self.audio_bitrate_frame.grid()
        else:
            self.audio_bitrate_frame.grid_remove()

    def _on_resolution_changed(self, event=None):
        """Show/hide custom resolution inputs."""
        if self.resolution_var.get() == "Custom":
            self.custom_res_frame.grid()
        else:
            self.custom_res_frame.grid_remove()

    def _browse_input(self):
        """Open file browser for input files."""
        filetypes = [
            ("Video files", "*.mp4 *.mkv *.avi *.mov *.webm *.flv *.wmv *.m4v"),
            ("All files", "*.*"),
        ]
        files = filedialog.askopenfilenames(title="Select Video Files", filetypes=filetypes)
        if files:
            self.input_files = [Path(f) for f in files]
            if len(self.input_files) == 1:
                self.input_label.config(text=self.input_files[0].name, foreground="black")
            else:
                self.input_label.config(text=f"{len(self.input_files)} files selected", foreground="black")

    def _clear_input(self):
        """Clear selected input files."""
        self.input_files = []
        self.input_label.config(text="No files selected", foreground="gray")
        self.drop_label.config(text="Drop video files here\nor click Browse")

    def _browse_output(self):
        """Open folder browser for output."""
        folder = filedialog.askdirectory(title="Select Output Folder")
        if folder:
            self.output_var.set(folder)

    def _get_encoder_info(self) -> EncoderInfo | None:
        """Get the currently selected encoder info."""
        display_name = self.encoder_var.get()
        for name, info in self.available_encoders.items():
            if info.display_name == display_name:
                return info
        return None

    def _get_encoder_name(self) -> str | None:
        """Get the FFmpeg encoder name for the selected encoder."""
        display_name = self.encoder_var.get()
        for name, info in self.available_encoders.items():
            if info.display_name == display_name:
                return name
        return None

    def _build_ffmpeg_command(self, input_path: Path, output_path: Path, duration: float | None = None) -> list[str]:
        """Build the FFmpeg command with all options."""
        encoder_name = self._get_encoder_name()
        encoder_info = self._get_encoder_info()

        cmd = ["ffmpeg", "-y", "-i", str(input_path)]

        # Video encoder
        cmd.extend(["-c:v", encoder_name])

        # Quality settings
        mode = self.quality_mode_var.get()
        if mode == "crf":
            quality_val = int(self.crf_var.get())
            if encoder_info.quality_param == "cq":
                cmd.extend(["-rc", "constqp", "-cq", str(quality_val)])
            elif encoder_info.quality_param == "global_quality":
                cmd.extend(["-global_quality", str(quality_val)])
            elif encoder_info.quality_param == "qp_i":
                cmd.extend(["-rc", "cqp", "-qp_i", str(quality_val), "-qp_p", str(quality_val), "-qp_b", str(quality_val)])
            else:
                cmd.extend(["-crf", str(quality_val)])
        elif mode == "filesize":
            # Calculate bitrate from target file size
            target_mb = float(self.target_size_var.get())
            if duration and duration > 0:
                # Target size in bits, minus ~10% for audio overhead
                audio_bitrate = 128 if self.audio_mode_var.get() == "reencode" else 0
                target_bits = target_mb * 8 * 1024 * 1024 * 0.95  # 95% for video
                video_bitrate = int((target_bits / duration - audio_bitrate * 1000) / 1000)
                video_bitrate = max(100, video_bitrate)  # Minimum 100 kbps
                logger.info(f"Target file size: {target_mb}MB, duration: {duration}s, calculated bitrate: {video_bitrate}k")
                cmd.extend(["-b:v", f"{video_bitrate}k"])
            else:
                # Fallback if duration unknown
                logger.warning("Duration unknown, using default bitrate for file size mode")
                cmd.extend(["-b:v", "1000k"])
        else:
            bitrate = self.bitrate_var.get()
            cmd.extend(["-b:v", f"{bitrate}k"])

        # Preset
        preset = self.preset_var.get()
        if encoder_name in ("h264_nvenc", "hevc_nvenc"):
            cmd.extend(["-preset", preset])
        elif encoder_name in ("h264_amf", "hevc_amf"):
            cmd.extend(["-quality", preset])
        else:
            cmd.extend(["-preset", preset])

        # Resolution
        # Note: libx264/libx265 require dimensions divisible by 2
        # We use scale + pad to ensure even dimensions after aspect ratio scaling
        resolution = self.resolution_var.get()
        scale_filter = None
        if resolution == "Custom":
            w = self.custom_width_var.get()
            h = self.custom_height_var.get()
            # Ensure even dimensions
            scale_filter = f"scale={w}:{h}:force_original_aspect_ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2"
        elif resolution != "Keep Original":
            res_value = self.RESOLUTIONS[resolution]
            if res_value:
                w, h = res_value.split("x")
                # Scale to fit, then ensure even dimensions
                scale_filter = f"scale={w}:{h}:force_original_aspect_ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2"

        # Frame rate
        fps = self.fps_var.get()
        fps_filter = None
        if fps != "Keep Original":
            fps_filter = f"fps={fps}"

        # Combine video filters
        vf_parts = [f for f in [scale_filter, fps_filter] if f]
        if vf_parts:
            cmd.extend(["-vf", ",".join(vf_parts)])

        # Audio settings
        audio_mode = self.audio_mode_var.get()
        if audio_mode == "reencode":
            cmd.extend(["-c:a", "aac", "-b:a", self.audio_bitrate_var.get()])
        elif audio_mode == "copy":
            cmd.extend(["-c:a", "copy"])
        else:
            cmd.append("-an")

        cmd.append(str(output_path))
        return cmd

    def _get_video_duration(self, path: Path) -> float | None:
        """Get video duration in seconds using ffprobe."""
        try:
            result = subprocess.run(
                [
                    "ffprobe", "-v", "quiet", "-print_format", "json",
                    "-show_format", str(path)
                ],
                capture_output=True, text=True, timeout=30
            )
            data = json.loads(result.stdout)
            return float(data["format"]["duration"])
        except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError, FileNotFoundError):
            return None

    def _parse_progress(self, line: str, duration: float | None) -> float | None:
        """Parse FFmpeg output to get progress percentage."""
        if duration is None:
            return None
        time_match = re.search(r"time=(\d+):(\d+):(\d+\.?\d*)", line)
        if time_match:
            h, m, s = time_match.groups()
            current = int(h) * 3600 + int(m) * 60 + float(s)
            return min(100, (current / duration) * 100)
        return None

    def _update_status(self, message: str, color: str = "gray"):
        """Update status label (thread-safe)."""
        self.root.after(0, lambda: self.status_var.set(message))
        self.root.after(0, lambda: self.status_label.config(foreground=color))

    def _update_progress(self, value: float):
        """Update progress bar (thread-safe)."""
        self.root.after(0, lambda: self.progress_var.set(value))

    def _append_result(self, text: str):
        """Append text to result area (thread-safe)."""
        def _append():
            self.result_text.config(state="normal")
            self.result_text.insert("end", text + "\n")
            self.result_text.see("end")
            self.result_text.config(state="disabled")
        self.root.after(0, _append)

    def _clear_result(self):
        """Clear result area."""
        self.result_text.config(state="normal")
        self.result_text.delete("1.0", "end")
        self.result_text.config(state="disabled")

    def _compression_finished(self, success: bool):
        """Called when compression completes (thread-safe)."""
        def _finish():
            self.is_compressing = False
            self.compress_btn.config(state="normal")
            self.cancel_btn.config(state="disabled")
            if success:
                self._update_status("Completed!", "green")
                self._play_chime(success=True)
            elif self.cancel_requested:
                self._update_status("Cancelled", "orange")
            else:
                self._update_status("Failed", "red")
                self._play_chime(success=False)
        self.root.after(0, _finish)

    def _show_logs(self):
        """Open a window showing the log file contents."""
        log_window = tk.Toplevel(self.root)
        log_window.title("Steve's Video Compressor - Logs")
        log_window.geometry("800x500")

        # Create frame with scrollbar
        frame = ttk.Frame(log_window)
        frame.pack(fill="both", expand=True, padx=10, pady=10)

        scrollbar = ttk.Scrollbar(frame)
        scrollbar.pack(side="right", fill="y")

        log_text = tk.Text(frame, wrap="none", yscrollcommand=scrollbar.set, font=("Courier", 9))
        log_text.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=log_text.yview)

        # Horizontal scrollbar
        h_scrollbar = ttk.Scrollbar(log_window, orient="horizontal", command=log_text.xview)
        h_scrollbar.pack(fill="x", padx=10)
        log_text.config(xscrollcommand=h_scrollbar.set)

        # Load log content
        try:
            with open(LOG_FILE, "r") as f:
                log_content = f.read()
            log_text.insert("1.0", log_content)
        except Exception as e:
            log_text.insert("1.0", f"Error reading log file: {e}")

        log_text.config(state="disabled")

        # Scroll to bottom
        log_text.see("end")

        # Button frame
        btn_frame = ttk.Frame(log_window)
        btn_frame.pack(fill="x", padx=10, pady=(0, 10))

        def refresh_logs():
            log_text.config(state="normal")
            log_text.delete("1.0", "end")
            try:
                with open(LOG_FILE, "r") as f:
                    log_text.insert("1.0", f.read())
            except Exception as e:
                log_text.insert("1.0", f"Error reading log file: {e}")
            log_text.config(state="disabled")
            log_text.see("end")

        ttk.Button(btn_frame, text="Refresh", command=refresh_logs).pack(side="left")
        ttk.Button(btn_frame, text="Close", command=log_window.destroy).pack(side="right")

    def _play_chime(self, success: bool = True):
        """Play a completion chime sound."""
        def _play():
            try:
                # Try system bell first
                self.root.bell()

                # Try to play a sound file using available tools
                sound_cmds = [
                    # PulseAudio
                    ["paplay", "/usr/share/sounds/freedesktop/stereo/complete.oga"],
                    # ALSA
                    ["aplay", "-q", "/usr/share/sounds/alsa/Front_Center.wav"],
                ]

                for cmd in sound_cmds:
                    try:
                        subprocess.run(cmd, capture_output=True, timeout=2)
                        logger.info(f"Played sound using: {cmd[0]}")
                        break
                    except (FileNotFoundError, subprocess.TimeoutExpired):
                        continue
            except Exception as e:
                logger.debug(f"Could not play chime: {e}")

        # Run in thread to not block UI
        threading.Thread(target=_play, daemon=True).start()

    def _start_compression(self):
        """Start the compression process."""
        if not self.input_files:
            messagebox.showwarning("No Input", "Please select input video files.")
            return

        self.is_compressing = True
        self.cancel_requested = False
        self.compress_btn.config(state="disabled")
        self.cancel_btn.config(state="normal")
        self._clear_result()
        self._update_progress(0)

        thread = threading.Thread(target=self._compress_files, daemon=True)
        thread.start()

    def _cancel_compression(self):
        """Cancel the current compression."""
        self.cancel_requested = True
        if self.current_process:
            self.current_process.terminate()

    def _compress_files(self):
        """Compress all input files (runs in background thread)."""
        logger.info("Starting compression thread")
        total_files = len(self.input_files)
        total_input_size = 0
        total_output_size = 0

        for i, input_path in enumerate(self.input_files):
            if self.cancel_requested:
                logger.info("Compression cancelled by user")
                break

            logger.info(f"Processing file {i+1}/{total_files}: {input_path}")
            self._update_status(f"Processing {i+1}/{total_files}: {input_path.name}")

            # Determine output path
            output_dir = self.output_var.get()
            if output_dir == "Same as input":
                output_dir = input_path.parent
            else:
                output_dir = Path(output_dir)

            suffix = self.suffix_var.get()
            container = self.container_var.get()
            output_path = output_dir / f"{input_path.stem}{suffix}{container}"
            logger.info(f"Output path: {output_path}")

            # Get duration for progress
            duration = self._get_video_duration(input_path)
            logger.info(f"Video duration: {duration}")

            # Build and run command
            cmd = self._build_ffmpeg_command(input_path, output_path, duration)
            logger.info(f"FFmpeg command: {' '.join(cmd)}")

            try:
                self.current_process = subprocess.Popen(
                    cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE,
                    text=True, bufsize=1
                )
                logger.info(f"FFmpeg process started with PID: {self.current_process.pid}")

                stderr_lines = []
                for line in self.current_process.stderr:
                    stderr_lines.append(line.rstrip())
                    if self.cancel_requested:
                        break
                    progress = self._parse_progress(line, duration)
                    if progress is not None:
                        overall = (i * 100 + progress) / total_files
                        self._update_progress(overall)

                self.current_process.wait()
                logger.info(f"FFmpeg process finished with return code: {self.current_process.returncode}")

                if self.current_process.returncode == 0 and output_path.exists():
                    input_size = input_path.stat().st_size / (1024 * 1024)
                    output_size = output_path.stat().st_size / (1024 * 1024)
                    reduction = (1 - output_size / input_size) * 100

                    total_input_size += input_size
                    total_output_size += output_size

                    logger.info(f"Compression successful: {input_size:.1f}MB → {output_size:.1f}MB ({reduction:.1f}%)")
                    self._append_result(
                        f"{input_path.name}: {input_size:.1f}MB → {output_size:.1f}MB ({reduction:.1f}% smaller)"
                    )
                elif not self.cancel_requested:
                    # Log the last 20 lines of FFmpeg stderr for debugging
                    logger.error(f"Compression failed for {input_path.name} with return code {self.current_process.returncode}")
                    logger.error("FFmpeg stderr (last 20 lines):")
                    for line in stderr_lines[-20:]:
                        logger.error(f"  {line}")

                    # Try to extract error message for user
                    error_msg = "FAILED"
                    for line in reversed(stderr_lines):
                        if "error" in line.lower() or "invalid" in line.lower():
                            error_msg = f"FAILED: {line.strip()[:50]}"
                            break
                    self._append_result(f"{input_path.name}: {error_msg}")

            except Exception as e:
                logger.error(f"Exception during compression: {e}")
                logger.error(traceback.format_exc())
                self._append_result(f"{input_path.name}: Error - {str(e)}")

        # Summary
        if total_files > 1 and total_input_size > 0:
            total_reduction = (1 - total_output_size / total_input_size) * 100
            self._append_result(f"\nTotal: {total_input_size:.1f}MB → {total_output_size:.1f}MB ({total_reduction:.1f}% smaller)")

        self._update_progress(100 if not self.cancel_requested else 0)
        self._compression_finished(not self.cancel_requested)


def main():
    logger.info("=" * 50)
    logger.info("Video Compressor starting")
    logger.info(f"Python version: {sys.version}")
    logger.info(f"HAS_DND: {HAS_DND}")
    logger.info("=" * 50)

    try:
        if HAS_DND:
            logger.info("Creating TkinterDnD root window")
            root = TkinterDnD.Tk()
        else:
            logger.info("Creating standard Tk root window")
            root = tk.Tk()

        logger.info("Creating VideoCompressorGUI instance")
        app = VideoCompressorGUI(root)

        logger.info("Starting mainloop")
        root.mainloop()
        logger.info("Mainloop ended normally")
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        logger.error(traceback.format_exc())
        raise


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"Unhandled exception: {e}")
        logger.error(traceback.format_exc())
        sys.exit(1)
