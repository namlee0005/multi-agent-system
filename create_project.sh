#!/bin/bash

# --- Script to create a new project from the base-project template ---

# Check if a project name was provided as an argument
if [ -z "$1" ]; then
  echo "Lỗi: Vui lòng cung cấp tên dự án."
  echo "Sử dụng: $0 <ten-du-an>"
  exit 1
fi

PROJECT_NAME=$1
TEMPLATE_DIR="./base-project"
# Set the default projects directory relative to the script's location
# This ensures it always points to the 'projects' folder in the workspace root
DEFAULT_PROJECTS_DIR="$(dirname "$0")/../projects"

# Use PROJECTS_DIR if set by the user, otherwise use the default
PROJECTS_BASE_DIR="${PROJECTS_DIR:-$DEFAULT_PROJECTS_DIR}"
TARGET_DIR="$PROJECTS_BASE_DIR/$PROJECT_NAME"

# Check if a project with that name already exists
if [ -d "$TARGET_DIR" ]; then
  echo "Lỗi: Dự án '$PROJECT_NAME' đã tồn tại."
  exit 1
fi

echo "Đang tạo dự án mới: $PROJECT_NAME..."

# Copy the entire template directory to the new project location
mkdir -p "$TARGET_DIR" && cp -r "$TEMPLATE_DIR/." "$TARGET_DIR"

echo "Đã tạo thành công dự án '$PROJECT_NAME' tại thư mục: $TARGET_DIR"
