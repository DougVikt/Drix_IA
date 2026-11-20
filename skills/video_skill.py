import subprocess
import os
import shutil
from pathlib import Path

def gerar_video_slideshow(image_folder, output_name="slideshow.mp4", duration=3, **kwargs):
    cfg = kwargs.get("config", {})
    if not cfg.get("skills", {}).get("generate_video", False):
        return "Video generation is disabled in config.yaml (skills.generate_video=false)."
    hd_root = kwargs.get("hd_root", Path("."))
    workspace = hd_root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    img_dir = Path(image_folder)
    if not img_dir.exists():
        return f"Image folder not found: {image_folder}"
    images = sorted(img_dir.glob("*.png")) + sorted(img_dir.glob("*.jpg")) + sorted(img_dir.glob("*.jpeg"))
    if not images:
        return f"No images found in {image_folder}"
    output_path = workspace / output_name
    ffmpeg = _find_ffmpeg()
    if ffmpeg:
        try:
            list_file = workspace / "_filelist.txt"
            with open(list_file, "w") as f:
                for img in images:
                    f.write(f"file '{img.resolve()}'\n")
                    f.write(f"duration {duration}\n")
            cmd = [str(ffmpeg), "-y", "-f", "concat", "-safe", "0",
                   "-i", str(list_file), "-vsync", "vfr", "-pix_fmt", "yuv420p",
                   str(output_path)]
            subprocess.run(cmd, capture_output=True, timeout=120)
            list_file.unlink(missing_ok=True)
            if output_path.exists():
                return f"Video slideshow created: {output_path}"
            return "FFmpeg failed to generate video."
        except Exception as e:
            return f"FFmpeg error: {e}"
    else:
        return "FFmpeg not found. Install FFmpeg or place the binary in ia_system/bin/"

def gerar_video_texto(texto, output_name="text_video.mp4", **kwargs):
    hd_root = kwargs.get("hd_root", Path("."))
    workspace = hd_root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    output_path = workspace / output_name
    ffmpeg = _find_ffmpeg()
    if not ffmpeg:
        return "FFmpeg not found. Install FFmpeg or place the binary in ia_system/bin/"
    escaped = texto.replace("'", "'\\''").replace(":", "\\:").replace("%", "%%")
    try:
        cmd = [str(ffmpeg), "-y", "-f", "lavfi", "-i", "color=c=black:s=1280x720:d=10",
               "-vf", f"drawtext=text='{escaped}':fontsize=24:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2",
               "-c:v", "libx264", "-pix_fmt", "yuv420p", str(output_path)]
        subprocess.run(cmd, capture_output=True, timeout=120)
        if output_path.exists():
            return f"Text video created: {output_path}"
        return "Failed to generate text video."
    except Exception as e:
        return f"Error generating text video: {e}"

def _find_ffmpeg():
    candidates = [
        shutil.which("ffmpeg"),
        str(Path(__file__).parent.parent / "ia_system" / "bin" / "ffmpeg.exe"),
        str(Path(__file__).parent.parent / "ia_system" / "bin" / "ffmpeg"),
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    return None