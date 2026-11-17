"""Local video evidence: bounded frame sampling and supplied sidecar subtitles.

This module does not perform ASR, describe pictures, upload files, or access a network.
"""
from __future__ import annotations

import html
import copy
import json
import math
import re
import subprocess
import time
import uuid
from pathlib import Path

FRAME_COUNT = 6
MAX_SUBTITLES = 200
TOTAL_TIMEOUT = 120
_VIDEO_SUFFIXES = {'.mp4', '.mov', '.mkv', '.avi', '.webm', '.m4v'}
_TIME = r'(?:\d{1,3}:)?\d{2}:\d{2}[.,]\d{1,3}'
_TIMING = re.compile(r'^\s*(' + _TIME + r')\s*-->\s*(' + _TIME + r')(?:\s+.*)?$')


def _find_tools(engine_root: Path):
    root = Path(engine_root).resolve()
    # Fixed project locations only; never run a PATH executable or accept an arbitrary URL.
    for directory in ('components/ffmpeg/bin', 'components/ffmpeg', 'runtime/ffmpeg/bin', 'runtime/ffmpeg'):
        folder = root / directory
        ffmpeg, ffprobe = folder / 'ffmpeg.exe', folder / 'ffprobe.exe'
        if ffmpeg.is_file() and ffprobe.is_file():
            if not ffmpeg.resolve().is_relative_to(root) or not ffprobe.resolve().is_relative_to(root):
                continue
            return ffmpeg, ffprobe
    raise ValueError('未找到项目内FFmpeg/ffprobe。请放入components/ffmpeg/bin或runtime/ffmpeg/bin后重试，未生成媒体观察。')


def _seconds(timestamp):
    parts = timestamp.replace(',', '.').split(':')
    if len(parts) == 2:
        hours, minutes, seconds = 0, int(parts[0]), float(parts[1])
    else:
        hours, minutes, seconds = int(parts[0]), int(parts[1]), float(parts[2])
    if minutes >= 60 or not 0 <= seconds < 60:
        raise ValueError('Invalid subtitle time')
    return hours * 3600 + minutes * 60 + seconds


def _subtitles(video: Path, duration: float):
    warnings = []
    candidates = []
    # Only the explicitly selected video's same-name adjacent files, not a directory crawl.
    for suffix in ('.srt', '.vtt'):
        path = video.with_suffix(suffix)
        if path.is_file():
            if path.resolve().parent != video.parent:
                warnings.append('跳过指向视频目录之外的字幕链接。')
                continue
            candidates.append(path)
    if not candidates:
        return [], ['没有找到同名相邻SRT/VTT字幕；未进行语音转写，不能据此判断全部口播或声音。']
    if len(candidates) > 1:
        warnings.append('同时存在SRT和VTT，本次只采用SRT；未合并重复字幕。')
    path = candidates[0]
    if path.stat().st_size > 2 * 1024 * 1024:
        return [], warnings + ['字幕超过2MiB，未读取；未进行语音转写。']
    raw = path.read_bytes()
    try:
        text = raw.decode('utf-16') if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else raw.decode('utf-8-sig')
    except UnicodeError:
        return [], warnings + ['字幕不是有效UTF-8或带BOM的UTF-16；未猜测编码，未进行语音转写。']
    records = []
    invalid = 0
    truncated = False
    blocks = re.split(r'\n[ \t]*\n', text.replace('\r\n', '\n').replace('\r', '\n'))
    for block in blocks:
        lines = block.strip().splitlines()
        if not lines or lines[0].startswith(('WEBVTT', 'NOTE', 'STYLE', 'REGION')):
            continue
        timing_index = next((i for i, line in enumerate(lines[:2]) if _TIMING.match(line)), None)
        if timing_index is None:
            invalid += 1
            continue
        match = _TIMING.match(lines[timing_index])
        try:
            start, end = _seconds(match[1]), _seconds(match[2])
        except (ValueError, IndexError):
            invalid += 1
            continue
        content = html.unescape(re.sub(r'<[^>]*>', '', '\n'.join(lines[timing_index + 1:]))).strip()
        if not content or start < 0 or end <= start or start >= duration:
            invalid += 1
            continue
        if end > duration:
            end = duration
            warnings.append('存在超出视频时长的字幕结束点，已裁到视频结尾。')
        if len(records) == MAX_SUBTITLES:
            truncated = True
            break
        records.append({'start': round(start, 3), 'end': round(end, 3), 'text': content})
    if truncated:
        warnings.append('字幕超过200段，只保留前200段；不是完整全文。')
    if invalid:
        warnings.append(f'跳过{invalid}段无有效时间或正文的字幕。')
    if not records:
        warnings.append('相邻字幕未解析出可用片段；未进行语音转写。')
    else:
        warnings.append('字幕来自用户提供的相邻文件，未与音轨逐句校对；不等于自动语音识别结果。')
    return records, list(dict.fromkeys(warnings))


def _run(command, deadline, label):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise ValueError('媒体提取达到总时间限制，已停止；未生成完整观察。')
    kwargs = {'stdin': subprocess.DEVNULL, 'stdout': subprocess.PIPE, 'stderr': subprocess.PIPE,
              'encoding': 'utf-8', 'errors': 'replace', 'timeout': min(25, remaining), 'shell': False}
    if hasattr(subprocess, 'CREATE_NO_WINDOW'):
        kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
    try:
        result = subprocess.run([str(x) for x in command], **kwargs)
    except subprocess.TimeoutExpired:
        raise ValueError(label + '超时，已停止该子进程。') from None
    except OSError:
        raise ValueError(label + '启动失败，请检查项目内工具和权限。') from None
    if result.returncode != 0:
        raise ValueError(label + '失败；文件可能损坏、格式不支持或解码不可用。')
    return result


def validated_speech(speech, duration):
    """Validate the ASR completion boundary without importing any ASR runtime.

    Return the full normalized segments. The original object remains available locally.
    Completion is a processing claim, never a transcription accuracy guarantee.
    """
    if not isinstance(speech, dict) or speech.get('complete') is not True:
        raise ValueError('语音识别未完整完成，不能作为完整口播依据。')
    status = speech.get('status')
    if status not in ('complete', 'no_audio', 'no_speech'):
        raise ValueError('语音识别状态无效或失败。')
    def number(value):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError('语音识别时间无效。')
        return float(value)
    audio = number(speech.get('audio_duration'))
    processed = number(speech.get('processed_duration'))
    if processed + .25 < audio or audio > duration + .25:
        raise ValueError('语音识别未覆盖完整音轨或超出视频时长。')
    segments = speech.get('segments')
    if not isinstance(segments, list):
        raise ValueError('语音识别片段须为数组。')
    if status == 'no_audio' and (audio != 0 or processed != 0 or segments):
        raise ValueError('无音轨状态与识别数据不一致。')
    if status == 'no_speech' and segments:
        raise ValueError('无可识别语音状态不能包含口播片段。')
    if status == 'complete' and (audio <= 0 or not segments):
        raise ValueError('完整口播状态缺少实际识别片段。')
    transcript = []
    previous_start = -1
    for segment in segments:
        if not isinstance(segment, dict):
            raise ValueError('语音识别片段须为对象。')
        start, end = number(segment.get('start')), number(segment.get('end'))
        text = segment.get('text')
        if (end <= start or start < previous_start or end > audio + .25 or end > duration + .25
                or start >= duration or not isinstance(text, str) or not text.strip()):
            raise ValueError('语音识别片段时间或正文无效。')
        previous_start = start
        row = {key: copy.deepcopy(segment[key]) for key in
               ('avg_logprob', 'no_speech_prob', 'uncertain') if key in segment}
        row.update(start=start, end=min(end, duration), text=text.strip(), source='asr')
        transcript.append(row)
    return transcript


def analyze_media(asset: dict, work_dir: Path, engine_root: Path, emit=None, speech=None) -> dict:
    if not isinstance(asset, dict) or not isinstance(asset.get('path'), str) or not asset['path'].strip():
        raise ValueError('缺少本机视频路径。')
    video = Path(asset['path']).expanduser().resolve()
    if not video.is_file() or video.suffix.lower() not in _VIDEO_SUFFIXES:
        raise ValueError('视频不存在或扩展名不在支持范围。')
    ffmpeg, ffprobe = _find_tools(engine_root)
    deadline = time.monotonic() + TOTAL_TIMEOUT
    if emit:
        emit({'stage': 'media', 'progress': 2, 'message': '正在本机读取视频尺寸和时长；不上传素材。'})
    probe = _run([ffprobe, '-v', 'error', '-protocol_whitelist', 'file,pipe',
                  '-show_entries', 'format=duration:stream=index,codec_type,width,height,duration:stream_disposition=attached_pic',
                  '-of', 'json', '-i', video], deadline, '视频信息读取')
    try:
        data = json.loads(probe.stdout)
        stream = next(s for s in data.get('streams', []) if s.get('codec_type') == 'video'
                      and not s.get('disposition', {}).get('attached_pic', 0)
                      and int(s.get('width', 0)) > 0 and int(s.get('height', 0)) > 0)
        width, height = int(stream['width']), int(stream['height'])
        stream_index = int(stream.get('index', 0))
        if stream_index < 0:
            raise ValueError()
        duration = float(data.get('format', {}).get('duration') or stream.get('duration'))
        if not math.isfinite(duration) or duration <= 0 or not 0 < width <= 65536 or not 0 < height <= 65536:
            raise ValueError()
    except (ValueError, TypeError, AttributeError, KeyError, StopIteration):
        raise ValueError('无法取得有效视频流、尺寸或有限时长；未生成模板观察。') from None
    root = Path(work_dir).resolve()
    try:
        root.mkdir(parents=True, exist_ok=True)
        output = root / ('media-' + uuid.uuid4().hex)
        output.mkdir(exist_ok=False)
    except OSError:
        raise ValueError('媒体工作目录不可写。') from None
    subtitles, warnings = _subtitles(video, duration)
    transcript = subtitles
    scope = 'sampled_frames_and_supplied_subtitles'
    if speech is not None:
        transcript = validated_speech(speech, duration)
        scope = {'complete': 'sampled_frames_and_full_audio_transcript',
                 'no_audio': 'sampled_frames_no_audio', 'no_speech': 'sampled_frames_no_speech'}[speech['status']]
        warnings = [warning.replace('；未进行语音转写，不能据此判断全部口播或声音。', '。')
                    .replace('未进行语音转写。', '未读取外部字幕。') for warning in warnings]
        warnings.append('语音为机器识别结果，完成表示音轨处理完整，不保证逐字准确；低置信片段需人工核对。')
    timestamps = [duration * (index + .5) / FRAME_COUNT for index in range(FRAME_COUNT)]
    if transcript and speech is not None:
        # Preserve uniform coverage, with at most two additional actual speech positions.
        for segment in (transcript[len(transcript) // 4], transcript[3 * len(transcript) // 4]):
            point = (segment['start'] + segment['end']) / 2
            if all(abs(point - existing) > .05 for existing in timestamps):
                timestamps.append(point)
        timestamps.sort()
    frames = []
    for index, timestamp in enumerate(timestamps):
        target = output / f'frame-{index + 1:02d}.jpg'
        try:
            _run([ffmpeg, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
                  '-protocol_whitelist', 'file,pipe', '-ss', f'{timestamp:.6f}', '-i', video,
                  '-map', f'0:{stream_index}', '-frames:v', '1', '-an', '-sn', '-dn',
                  '-vf', 'scale=1280:720:force_original_aspect_ratio=decrease',
                  '-threads', '1', '-q:v', '3', target], deadline, '视频抽帧')
            if not target.is_file() or target.stat().st_size == 0:
                raise ValueError('抽帧未生成文件。')
            with target.open('rb') as image:
                if image.read(2) != b'\xff\xd8':
                    raise ValueError('抽帧未生成JPEG。')
            frames.append({'timestamp': round(timestamp, 3), 'path': str(target)})
        except ValueError:
            warnings.append(f'{timestamp:.3f}秒处未取得有效画面；不补造帧或观察。')
        if emit:
            emit({'stage': 'media', 'progress': 5 + int((index + 1) * 90 / len(timestamps)),
                  'message': f'已处理抽样位置{index + 1}/{len(timestamps)}，取得{len(frames)}张画面。'})
    if not frames:
        raise ValueError('没有取得任何有效JPEG帧，媒体证据提取失败；未生成模板内容。')
    warnings.insert(0, '仅抽样画面，未完整观看视频，未进行画面语义识别或OCR；可能漏掉短暂事件和屏幕文字。' if speech is not None else
                    '仅按时间均匀抽样画面，未完整观看视频，未进行画面语义识别、OCR或语音转写；可能漏掉短暂事件和屏幕文字。')
    result = {'duration': duration, 'width': width, 'height': height, 'frames': frames,
            'transcript': transcript, 'analysis_scope': scope,
            'warnings': list(dict.fromkeys(warnings))}
    if speech is not None:
        result.update(speech=copy.deepcopy(speech), supplied_subtitles=subtitles)
    return result
