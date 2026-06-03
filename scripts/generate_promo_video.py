"""
Generate a PPT-style promotional video for Binance Smart Copy.
Uses MoviePy for animation + Edge-TTS for Chinese voice-over.
Output: promo_video.mp4 (1920x1080, 30fps)
"""

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

import numpy as np
from moviepy import (
    AudioFileClip,
    ColorClip,
    CompositeVideoClip,
    concatenate_videoclips,
    ImageClip,
    TextClip,
    vfx,
)
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
OUTPUT = Path(__file__).resolve().parent.parent / "promo_video.mp4"
W, H = 1920, 1080
FPS = 30
BG_DARK = (30, 32, 38)        # #1e2026
BG_CARD = (40, 44, 52)        # #282c34
YELLOW = (243, 186, 47)       # #f3ba2f
WHITE = (240, 240, 245)
GRAY = (150, 155, 165)
GREEN = (14, 203, 129)

FONT_BOLD = "Arial-Bold"      # will fall back to Arial on Windows
FONT_REGULAR = "Arial"

# ---- Voice-over script (each line = one subtitle / voice segment) ----------
# Format: [(start_seconds, duration, "Chinese text", "English subtitle fallback"), ...]
# We'll build timing from cumulative durations.
SCRIPT = [
    (8, "欢迎来到 Binance Smart Copy —— 你的智能合约跟单助手。"),
    (10, "你是否在币安上发现了优秀的交易员，却因为没时间盯盘而错过跟单机会？"),
    (8, "现在，你只需要配置一次，脚本就能 7×24 小时自动运行。"),
    (10, "它会实时抓取目标交易员的持仓变化，按比例计算你的跟单仓位，并通过币安 API 自动开仓和平仓。"),
    (8, "内置完善的风控体系：支持单笔最大限额、最小下单保护、以及强制兜底开关。"),
    (6, "支持本地代理配置，方便国内用户顺畅访问币安 API。"),
    (6, "所有交易行为自动记录到 CSV 日志，方便复盘与分析。"),
    (7, "三步快速开始：填写 .env 配置、安装依赖、运行脚本。"),
    (8, "首次运行自动弹出浏览器，登录币安后自动保存凭证，无需手动抓取 Cookie。"),
    (7, "项目完全开源，欢迎前往 GitHub 给它一个 Star，Fork 并开始你的定制化改造。"),
    (6, "详情请查看仓库 README 或发送邮件至 weimr30@gmail.com"),
    (5, "风险提示：量化交易有风险，请充分测试后再投入实盘。祝交易顺利！"),
]


def find_chinese_font():
    """Try to find a Chinese-capable font on the system."""
    candidates = [
        "C:/Windows/Fonts/msyh.ttc",       # Microsoft YaHei
        "C:/Windows/Fonts/msyhbd.ttc",     # Microsoft YaHei Bold
        "C:/Windows/Fonts/simhei.ttf",     # SimHei
        "C:/Windows/Fonts/simsun.ttc",     # SimSun
        "C:/Windows/Fonts/STKAITI.TTF",    # STKaiti
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


CN_FONT = find_chinese_font() or "Arial"
print(f"Using Chinese font: {CN_FONT}")


# ---------------------------------------------------------------------------
# Slide image generation (Pillow – crisp text rendering for each slide)
# ---------------------------------------------------------------------------
def make_slide_image(
    title: str,
    subtitle: str = "",
    bullets: list[str] | None = None,
    footer: str = "",
    highlight: bool = False,
) -> Image.Image:
    """Render a dark-themed slide and return a PIL Image."""
    img = Image.new("RGB", (W, H), BG_DARK)
    draw = ImageDraw.Draw(img)

    # Decorative top bar
    draw.rectangle([(0, 0), (W, 6)], fill=YELLOW)

    # Try loading fonts
    try:
        font_title = ImageFont.truetype(CN_FONT, 64)
        font_sub = ImageFont.truetype(CN_FONT, 32)
        font_bullet = ImageFont.truetype(CN_FONT, 36)
        font_footer = ImageFont.truetype(CN_FONT, 28)
        font_big = ImageFont.truetype(CN_FONT, 80)
    except Exception:
        font_title = ImageFont.load_default()
        font_sub = font_bullet = font_footer = font_big = font_title

    # Title
    if highlight:
        # Large centered title for hero slides
        bbox = draw.textbbox((0, 0), title, font=font_big)
        tw = bbox[2] - bbox[0]
        draw.text(((W - tw) / 2, 340), title, fill=YELLOW, font=font_big)
    else:
        draw.text((120, 80), title, fill=YELLOW, font=font_title)

    # Subtitle
    if subtitle:
        draw.text((120, 170), subtitle, fill=GRAY, font=font_sub)

    # Bullet points
    if bullets:
        y = 280
        for b in bullets:
            # Bullet marker
            draw.ellipse([(128, y + 12), (144, y + 28)], fill=YELLOW)
            draw.text((170, y), b, fill=WHITE, font=font_bullet)
            y += 70

    # Divider line
    if not highlight:
        draw.rectangle([(120, 940), (320, 944)], fill=YELLOW)

    # Footer
    if footer:
        draw.text((120, 980), footer, fill=GRAY, font=font_footer)

    # Right-side logo area
    logo_text = "BSC"
    try:
        font_logo = ImageFont.truetype(CN_FONT, 48)
    except Exception:
        font_logo = font_title
    bbox = draw.textbbox((0, 0), logo_text, font=font_logo)
    lw = bbox[2] - bbox[0]
    draw.text((W - lw - 60, 50), logo_text, fill=(60, 62, 68), font=font_logo)

    return img


# ---------------------------------------------------------------------------
# Generate all slide images
# ---------------------------------------------------------------------------
def generate_slides() -> list[Path]:
    """Create slide PNGs, return list of file paths."""
    tmp = Path(tempfile.mkdtemp(prefix="bsc_slides_"))
    slides_data = [
        # Hero / title slide
        {
            "title": "Binance Smart Copy",
            "subtitle": "智能合约跟单机器人",
            "bullets": None,
            "footer": "GitHub: lostmejava/binance-smart-copy",
            "highlight": True,
        },
        # Problem
        {
            "title": "🤔 你是否遇到过这些问题？",
            "subtitle": "",
            "bullets": [
                "发现了优秀的交易员，却没有时间盯盘",
                "手动跟单总是慢半拍，错失最佳入场时机",
                "仓位计算麻烦，风控难以精确执行",
            ],
            "footer": "Binance Smart Copy · 让跟单自动化",
            "highlight": False,
        },
        # Solution overview
        {
            "title": "⚡ 自动化跟单解决方案",
            "subtitle": "",
            "bullets": [
                "实时抓取目标交易员持仓变化",
                "按资金比例自动计算跟单仓位",
                "通过币安 API 自动开仓 / 平仓",
                "7×24 小时无人值守运行",
            ],
            "footer": "Binance Smart Copy · 让跟单自动化",
            "highlight": False,
        },
        # Risk control
        {
            "title": "🛡️ 内置风控体系",
            "subtitle": "",
            "bullets": [
                "MAX_USDT_PER_ORDER — 单笔最大订单限额",
                "MIN_USDT_PER_ORDER — 最小下单保护",
                "FORCE_MIN_ORDER — 强制兜底开关",
                "POLL_INTERVAL — 可调节轮询频率",
            ],
            "footer": "Binance Smart Copy · 安全第一",
            "highlight": False,
        },
        # Features
        {
            "title": "🔧 更多功能",
            "subtitle": "",
            "bullets": [
                "支持本地代理配置，国内用户友好",
                "交易日志自动记录到 CSV 文件",
                "首次运行自动弹出浏览器，保存登录凭证",
                "纯 Python 实现，无复杂依赖",
            ],
            "footer": "Binance Smart Copy · 功能完善",
            "highlight": False,
        },
        # Quick start
        {
            "title": "🚀 三步快速开始",
            "subtitle": "",
            "bullets": [
                "1. 克隆仓库，填写 .env 配置文件",
                "2. pip install -r requirements.txt",
                "3. python binance-smart-copy.py",
            ],
            "footer": "从零到运行，不到 5 分钟",
            "highlight": False,
        },
        # CTA
        {
            "title": "⭐ 开源 & 社区",
            "subtitle": "",
            "bullets": [
                "前往 GitHub 给项目点一个 Star",
                "Fork 仓库，开始你的定制化改造",
                "欢迎提交 Issue 和 Pull Request",
            ],
            "footer": "GitHub: lostmejava/binance-smart-copy",
            "highlight": False,
        },
        # Outro
        {
            "title": "谢谢观看！",
            "subtitle": "Happy Trading!",
            "bullets": None,
            "footer": "联系邮箱：weimr30@gmail.com",
            "highlight": True,
        },
    ]

    paths = []
    for i, sd in enumerate(slides_data):
        img = make_slide_image(**sd)
        p = tmp / f"slide_{i:02d}.png"
        img.save(str(p))
        paths.append(p)

    print(f"Generated {len(paths)} slides in {tmp}")
    return paths, tmp


# ---------------------------------------------------------------------------
# Text-to-speech via Windows native TTS (pyttsx3)
# ---------------------------------------------------------------------------
def generate_audio() -> tuple[Path, Path]:
    """Generate voice-over audio via Windows SAPI5 (offline).
    Returns (audio_path, tmp_dir).
    """
    import pyttsx3

    tmp = Path(tempfile.mkdtemp(prefix="bsc_audio_"))
    lines = [seg[1] for seg in SCRIPT]
    combined = " ".join(lines)

    print("  Initializing Windows TTS engine...")
    engine = pyttsx3.init()

    # Try to set a Chinese voice
    voices = engine.getProperty("voices")
    cn_voice = None
    for v in voices:
        name = v.name.lower()
        if any(kw in name for kw in ["chinese", "chines", "simplified", "mandarin", "kangkang", "huihui", "yaoyao"]):
            cn_voice = v.id
            print(f"  Found Chinese voice: {v.name}")
            break
    if cn_voice:
        engine.setProperty("voice", cn_voice)
    else:
        # Fallback: list all and pick first non-English
        for v in voices:
            if "english" not in v.name.lower():
                cn_voice = v.id
                print(f"  Using fallback voice: {v.name}")
                break
        if cn_voice:
            engine.setProperty("voice", cn_voice)
        else:
            print("  Warning: no Chinese voice found, using default")

    engine.setProperty("rate", 160)  # slightly slower for clarity

    audio_path = tmp / "voice.wav"
    print(f"  Generating speech ({len(combined)} chars)...")
    engine.save_to_file(combined, str(audio_path))
    engine.runAndWait()
    engine.stop()

    print(f"  Audio saved to {audio_path}")
    return audio_path, tmp


# ---------------------------------------------------------------------------
# Build video clips
# ---------------------------------------------------------------------------
def build_video(slide_paths: list[Path], audio_path: Path) -> None:
    """Compose slides + audio + subtitles into final video."""
    from moviepy.audio.io.AudioFileClip import AudioFileClip

    # Load audio
    audio = AudioFileClip(str(audio_path))
    total_duration = audio.duration
    print(f"Audio duration: {total_duration:.1f}s")

    # Calculate slide durations – spread across audio timeline
    # We'll use the script's segment durations as a proportional guide
    seg_durations = [seg[0] for seg in SCRIPT]
    seg_total = sum(seg_durations)
    # Scale to actual audio duration
    scale = total_duration / seg_total

    slide_count = len(slide_paths)
    # Distribute segments to slides (there are 12 segments for 8 slides)
    # Map: slide 0 gets segments 0,1; slide 1 gets segment 2; slide 2 gets segment 3;
    #       slide 3 gets segments 4,5,6; slide 4 gets segment 7; slide 5 gets segment 8;
    #       slide 6 gets segments 9,10; slide 7 gets segment 11
    seg_to_slide = [0, 0, 1, 2, 3, 3, 3, 4, 5, 6, 6, 7]

    # Build clip start times
    slide_starts = []
    current = 0.0
    for s in range(slide_count):
        slide_starts.append(current)
        dur = sum(
            seg_durations[i] * scale
            for i, sl in enumerate(seg_to_slide)
            if sl == s
        )
        current += dur
    # Fix last slide end
    slide_durations = []
    for i in range(slide_count):
        start = slide_starts[i]
        if i < slide_count - 1:
            end = slide_starts[i + 1]
        else:
            end = total_duration
        slide_durations.append(end - start)

    print("Slide timings:")
    for i, (s, d) in enumerate(zip(slide_starts, slide_durations)):
        print(f"  Slide {i}: {s:.1f}s – {s+d:.1f}s ({d:.1f}s)")

    # Create clips for each slide
    clips = []
    for i, (path, dur) in enumerate(zip(slide_paths, slide_durations)):
        ic = ImageClip(str(path), duration=dur)

        # Add subtle zoom-in effect (Ken Burns)
        if i > 0:  # skip hero slide
            ic = ic.resized(lambda t: 1.0 + 0.03 * t / max(dur, 0.1))

        # Fade-in for each slide
        ic = ic.with_effects([vfx.FadeIn(0.4), vfx.FadeOut(0.4)])

        clips.append(ic)

    # Concatenate all slide clips
    final = concatenate_videoclips(clips, method="compose")
    final = final.with_audio(audio)

    # Write output
    print(f"Rendering video to {OUTPUT}...")
    final.write_videofile(
        str(OUTPUT),
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        preset="medium",
        bitrate="5000k",
    )
    print(f"Done! Video saved to {OUTPUT}")


# ---------------------------------------------------------------------------
# Alternative: simpler approach using only ImageClip + text overlays
# ---------------------------------------------------------------------------
def build_video_with_subtitles(
    slide_paths: list[Path], audio_path: Path
) -> None:
    """Build video with burned-in subtitles using MoviePy TextClip."""
    from moviepy.audio.io.AudioFileClip import AudioFileClip

    audio = AudioFileClip(str(audio_path))
    total_duration = audio.duration

    seg_durations = [seg[0] for seg in SCRIPT]
    seg_total = sum(seg_durations)
    scale = total_duration / seg_total

    seg_to_slide = [0, 0, 1, 2, 3, 3, 3, 4, 5, 6, 6, 7]
    slide_count = len(slide_paths)

    # Compute slide timings
    slide_starts = []
    current = 0.0
    for s in range(slide_count):
        slide_starts.append(current)
        dur = sum(
            seg_durations[i] * scale
            for i, sl in enumerate(seg_to_slide)
            if sl == s
        )
        current += dur

    slide_durations = []
    for i in range(slide_count):
        start = slide_starts[i]
        end = slide_starts[i + 1] if i < slide_count - 1 else total_duration
        slide_durations.append(end - start)

    # Compute segment start times (for subtitles)
    seg_starts = []
    t = 0.0
    for d in seg_durations:
        seg_starts.append(t)
        t += d * scale

    # Build slide clips
    slide_clips = []
    for i, (path, dur) in enumerate(zip(slide_paths, slide_durations)):
        ic = ImageClip(str(path), duration=dur)
        if i > 0:
            ic = ic.resized(lambda t, d=dur: 1.0 + 0.03 * t / max(d, 0.1))
        ic = ic.with_effects([vfx.FadeIn(0.3), vfx.FadeOut(0.3)])
        slide_clips.append(ic.with_start(slide_starts[i]))

    # Build subtitle clips
    subtitle_clips = []
    for i, seg in enumerate(SCRIPT):
        if i < len(seg_starts):
            t_start = seg_starts[i]
            t_end = t_start + seg[0] * scale
            if i < len(seg_starts) - 1:
                t_end = min(t_end, seg_starts[i + 1] - 0.05)
            else:
                t_end = min(t_end, total_duration)

            try:
                txt = TextClip(
                    text=seg[1],
                    font=CN_FONT,
                    font_size=38,
                    color="white",
                    stroke_color="black",
                    stroke_width=2,
                    size=(W - 200, None),
                    method="caption",
                )
                txt = txt.with_position(("center", H - 160))
                txt = txt.with_start(t_start)
                txt = txt.with_duration(t_end - t_start)
                txt = txt.with_effects([vfx.FadeIn(0.15), vfx.FadeOut(0.15)])
                subtitle_clips.append(txt)
            except Exception as e:
                print(f"  Warning: subtitle {i} failed: {e}")

    # Compose everything on a black background
    bg = ColorClip((W, H), BG_DARK, duration=total_duration)
    final = CompositeVideoClip([bg] + slide_clips + subtitle_clips)
    final = final.with_audio(audio)

    print(f"Rendering video to {OUTPUT} (this may take a few minutes)...")
    final.write_videofile(
        str(OUTPUT),
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        preset="medium",
        bitrate="5000k",
    )
    print(f"Done! Video saved to {OUTPUT}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 60)
    print("Binance Smart Copy - Promo Video Generator")
    print("=" * 60)

    # Step 1: Generate slides
    print("\n[1/3] Generating slide images...")
    slide_paths, slide_tmp = generate_slides()

    # Step 2: Generate voice-over
    print("\n[2/3] Generating voice-over via Windows TTS...")
    audio_path, audio_tmp = generate_audio()

    # Step 3: Compose video
    print("\n[3/3] Composing final video...")
    build_video_with_subtitles(slide_paths, audio_path)

    # Cleanup
    import shutil
    shutil.rmtree(slide_tmp, ignore_errors=True)
    shutil.rmtree(audio_tmp, ignore_errors=True)
    print("\nAll done!")


if __name__ == "__main__":
    main()
