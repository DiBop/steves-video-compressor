#!/bin/bash
# Steve's Video Compressor Launcher
# Starts the video compressor GUI in a Docker container

CONTAINER_NAME="video-compressor"
IMAGE_NAME="video-compressor"

# Check if container exists
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    # Check if it's running
    if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        echo "Video Compressor is already running."
        exit 0
    else
        # Container exists but stopped - remove and recreate
        echo "Removing old container..."
        docker rm "$CONTAINER_NAME" > /dev/null
    fi
fi

# Allow X11 connections from Docker
xhost +local:docker > /dev/null 2>&1

# Launch container
echo "Starting Video Compressor..."
docker run -d \
    --name "$CONTAINER_NAME" \
    -e DISPLAY="$DISPLAY" \
    -e PULSE_SERVER="unix:${XDG_RUNTIME_DIR}/pulse/native" \
    -v /tmp/.X11-unix:/tmp/.X11-unix \
    -v "${XDG_RUNTIME_DIR}/pulse/native:${XDG_RUNTIME_DIR}/pulse/native" \
    -v "$HOME:/host_home" \
    -v "/media:/media" \
    "$IMAGE_NAME" > /dev/null

if [ $? -eq 0 ]; then
    echo "Video Compressor started successfully!"
    echo ""
    echo "Tips:"
    echo "  - Your home folder is at /host_home inside the app"
    echo "  - External drives are at /media"
    echo ""
    echo "Commands:"
    echo "  Stop:    docker stop $CONTAINER_NAME"
    echo "  Logs:    docker exec $CONTAINER_NAME cat /app/video_compressor.log"
    echo "  Restart: $0"
else
    echo "Failed to start Video Compressor"
    exit 1
fi
