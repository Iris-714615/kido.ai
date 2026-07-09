"""TTS 语音合成服务：将文本转为语音音频。

支持：
- DashScope cosyvoice（阿里云通义语音合成）
- Fallback 模式（返回最简 WAV 静音，让前端降级到浏览器内置 TTS）
"""
from __future__ import annotations

import logging
import struct
from io import BytesIO

from app.core.settings import get_settings

logger = logging.getLogger(__name__)

# 最小有效 WAV 文件（44 字节头 + 1 字节数据 = 45 字节），22050Hz 单声道 16bit
_SILENT_WAV: bytes | None = None


def _build_silent_wav(duration_sec: float = 0.1, sample_rate: int = 22050) -> bytes:
    """生成最短的静音 WAV 文件作为 fallback。"""
    num_samples = int(duration_sec * sample_rate)
    data_size = num_samples * 2  # 16bit = 2 bytes per sample

    buf = BytesIO()
    # RIFF header
    buf.write(b'RIFF')
    buf.write(struct.pack('<I', 36 + data_size))
    buf.write(b'WAVE')
    # fmt chunk
    buf.write(b'fmt ')
    buf.write(struct.pack('<IHHIIHH', 16, 1, 1, sample_rate, sample_rate * 2, 2, 16))
    # data chunk
    buf.write(b'data')
    buf.write(struct.pack('<I', data_size))
    buf.write(b'\x00' * data_size)
    return buf.getvalue()


def synthesize(text: str, voice: str | None = None) -> bytes:
    """将文本合成为语音音频，返回 WAV 格式字节。

    Args:
        text: 要合成的文本（限 500 字以内）
        voice: 音色名称（可选，默认用 settings.tts_voice）

    Returns:
        WAV 格式的音频字节

    Raises:
        ValueError: 文本为空或超长
    """
    if not text or not text.strip():
        raise ValueError("文本不能为空")
    if len(text) > 500:
        raise ValueError("文本长度超过 500 字限制")

    settings = get_settings()
    provider = settings.tts_provider
    voice_name = voice or settings.tts_voice

    if provider == "dashscope" and settings.dashscope_api_key:
        try:
            return _synthesize_dashscope(text, voice_name)
        except Exception as exc:
            logger.error("DashScope TTS failed: %s, fallback to silent", exc, exc_info=True)
            return _get_silent_wav()
    else:
        # Fallback 模式：返回静音 WAV，前端应降级到浏览器内置 speechSynthesis
        logger.info("[TTS Fallback] text=%r, returning silent WAV", text[:50])
        return _get_silent_wav()


def _get_silent_wav() -> bytes:
    global _SILENT_WAV
    if _SILENT_WAV is None:
        settings = get_settings()
        _SILENT_WAV = _build_silent_wav(0.1, settings.tts_sample_rate)
    return _SILENT_WAV


def _synthesize_dashscope(text: str, voice: str) -> bytes:
    """调用 DashScope cosyvoice 语音合成。

    使用子进程运行 dashscope SDK，通过临时文件传递音频字节，
    避免 uvicorn 事件循环与 WebSocket SDK 的冲突以及管道问题。
    返回 WAV 格式音频。
    """
    import os
    import subprocess
    import sys
    import tempfile

    settings = get_settings()

    # 创建临时文件路径供子进程写入音频
    fd, tmp_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)

    try:
        # 子进程脚本：合成后将音频写入临时文件，错误写入 debug 文件
        debug_path = tmp_path + ".debug"
        script = (
            "import dashscope\n"
            "from dashscope.audio.tts_v2 import SpeechSynthesizer, AudioFormat\n"
            "import sys\n"
            f"dashscope.api_key = {settings.dashscope_api_key!r}\n"
            "synth = SpeechSynthesizer("
            f"model={settings.tts_model!r}, "
            f"voice={voice!r}, "
            "format=AudioFormat.WAV_22050HZ_MONO_16BIT)\n"
            "try:\n"
            f"    result = synth.call({text!r})\n"
            "    if result:\n"
            f"        with open({tmp_path!r}, 'wb') as f:\n"
            "            f.write(result)\n"
            "    else:\n"
            f"        with open({debug_path!r}, 'w') as f:\n"
            "            f.write('result is None, last_response=' + str(synth.last_response))\n"
            "except Exception as e:\n"
            f"    with open({debug_path!r}, 'w') as f:\n"
            "        f.write('exception: ' + str(e) + ', last_response=' + str(getattr(synth, 'last_response', None)))\n"
        )

        proc = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            timeout=30,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", errors="replace")
            raise RuntimeError(f"DashScope TTS subprocess failed: {err}")

        debug_info = ""
        if os.path.exists(tmp_path + ".debug"):
            with open(tmp_path + ".debug", "r") as f:
                debug_info = f.read()
        if not os.path.exists(tmp_path) or os.path.getsize(tmp_path) == 0:
            err = proc.stderr.decode("utf-8", errors="replace")
            raise RuntimeError(f"DashScope TTS returned no audio (stderr: {err}, debug: {debug_info})")

        with open(tmp_path, "rb") as f:
            audio_data = f.read()
        return audio_data
    finally:
        for path in [tmp_path, tmp_path + ".debug"]:
            try:
                os.unlink(path)
            except OSError:
                pass
