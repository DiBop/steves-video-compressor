FROM python:3.11-slim

# Install tkinter, FFmpeg, X11 dependencies, and sound utilities
RUN apt-get update && apt-get install -y \
    python3-tk \
    ffmpeg \
    libx11-6 \
    libxext6 \
    libxrender1 \
    wget \
    pulseaudio-utils \
    sound-theme-freedesktop \
    && rm -rf /var/lib/apt/lists/*

# Install tkinterdnd2 for drag-and-drop support (includes bundled tkdnd)
RUN pip install --no-cache-dir tkinterdnd2

WORKDIR /app

COPY video_compressor_gui.py .

# Create a directory for video files to be mounted
RUN mkdir /videos

CMD ["python", "video_compressor_gui.py"]
