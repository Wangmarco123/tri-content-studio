"""Whole selected audio ASR, isolated GPU/CPU workers, local models only."""
from __future__ import annotations
import hashlib
import importlib.util
from importlib.metadata import version, PackageNotFoundError
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import wave

from .ai_provider import GenerationCancelled

MODEL='large-v3-turbo'
MODEL_FOLDER='faster-whisper-large-v3-turbo'
SETTINGS_VERSION='whole-audio-v4-container-time-pad-temp0-prevfalse-reject-tail'


def _cancel(cancel):
    if cancel and cancel():raise GenerationCancelled('已取消完整音轨转写')


def _emit(emit,progress,message,stage='transcribe'):
    if emit:emit({'stage':stage,'progress':max(0,min(100,progress)),'message':message})


def _atomic_json(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.tmp-'+str(os.getpid()))
    temp.write_text(json.dumps(data,ensure_ascii=False,allow_nan=False),encoding='utf-8')
    os.replace(temp,path)


def _run_command(command,cancel=None,timeout=60):
    _cancel(cancel)
    process=subprocess.Popen([str(v) for v in command],stdout=subprocess.PIPE,stderr=subprocess.PIPE,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    deadline=time.monotonic()+timeout
    try:
        while time.monotonic()<deadline:
            _cancel(cancel)
            try:
                stdout,stderr=process.communicate(timeout=.2)
                if process.returncode:raise ValueError('音轨读取或转换失败；未将局部音轨作为完整结果')
                return stdout
            except subprocess.TimeoutExpired:pass
        raise ValueError('音轨处理超时；未生成完整转写')
    finally:
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=3)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)
        for stream in (process.stdout,process.stderr):
            if stream is not None:stream.close()


def _tools(root):
    for relative in ('runtime/ffmpeg/bin','components/ffmpeg/bin','runtime/ffmpeg','components/ffmpeg'):
        folder=Path(root)/relative
        if (folder/'ffmpeg.exe').is_file() and (folder/'ffprobe.exe').is_file():
            if folder.resolve().is_relative_to(Path(root).resolve()):return folder/'ffmpeg.exe',folder/'ffprobe.exe'
    raise ValueError('缺少软件内FFmpeg/ffprobe，不能读取完整音轨')


def probe_audio(video,engine_root,cancel=None):
    _,probe=_tools(engine_root)
    data=json.loads(_run_command([probe,'-v','error','-show_streams','-show_format','-of','json',video],cancel,30))
    tracks=[s for s in data.get('streams',[]) if s.get('codec_type')=='audio']
    if not tracks:return None
    chosen=next((s for s in tracks if s.get('disposition',{}).get('default')==1),tracks[0])
    container=data.get('format',{})
    origin=_number(container.get('start_time'),0)
    start=_number(chosen.get('start_time'),origin)
    videos=[s for s in data.get('streams',[]) if s.get('codec_type')=='video']
    warnings=[]
    if _number(container.get('start_time'),None) is None:warnings.append('容器未报告start_time，按FFmpeg默认相对零点处理。')
    if _number(chosen.get('start_time'),None) is None:warnings.append('音轨未报告start_time，按容器起点处理，时间对齐尚有来源限制。')
    return {'index':int(chosen['index']),'duration':chosen.get('duration') or container.get('duration'),
        'audio_start_time':start,'format_start_time':origin,
        'video_start_time':_number(videos[0].get('start_time'),None) if videos else None,
        'alignment_warnings':warnings}


def extract_audio(video,track,work_dir,engine_root,cancel=None):
    ffmpeg,_=_tools(engine_root);output=Path(work_dir)/'audio.wav'
    # Input -ss (without -seek_timestamp) is relative to format.start_time,
    # exactly the timeline used by media.py's sampled frames.
    offset=_number(track.get('audio_start_time'),0)-_number(track.get('format_start_time'),0)
    if offset < -1/16000:
        raise ValueError('所选音轨早于容器相对零点，当前时间轴不支持；未裁掉负时刻口播，请先规范化源文件')
    padding_samples=max(0,round(offset*16000))
    try:duration=float(track.get('duration') or 0)
    except (ValueError,TypeError):duration=0
    timeout=max(180,min(3600,duration*3+120)) if math.isfinite(duration) else 180
    # No -t/-ss: decode the entire selected default audio stream, not its first N seconds.
    audio_filter=f'asetpts=PTS-STARTPTS,aresample=16000,adelay={padding_samples}S:all=1'
    _run_command([ffmpeg,'-nostdin','-y','-v','error','-xerror','-i',video,'-map',f"0:{track['index']}",'-vn','-af',audio_filter,'-ac','1','-ar','16000','-c:a','pcm_s16le',output],cancel,timeout)
    with wave.open(str(output),'rb') as wav:
        duration=wav.getnframes()/wav.getframerate()
    if not math.isfinite(duration) or duration<0:raise ValueError('解码后的音轨时长无效')
    return output,duration


def is_digital_silence(audio,cancel=None):
    """Exact all-zero PCM only; never suppress quiet speech via an energy threshold."""
    with wave.open(str(audio),'rb') as source:
        if source.getsampwidth()!=2 or source.getnchannels()!=1:raise ValueError('音轨不是约定的单声道PCM16')
        while True:
            _cancel(cancel)
            data=source.readframes(65536)
            if not data:return True
            if data.strip(b'\x00'):return False


def model_path(engine_root):
    root=Path(engine_root).resolve()
    for relative in ('runtime/asr/models','components/asr/models'):
        folder=root/relative/MODEL_FOLDER
        if folder.is_dir() and folder.resolve().is_relative_to(root):
            required=('model.bin','config.json','tokenizer.json','vocabulary.json')
            if all((folder/f).is_file() and (folder/f).stat().st_size>0 for f in required):return folder
    raise ValueError('本地large-v3-turbo模型缺失或不完整；软件不会隐式联网下载模型')


def asr_status(engine_root):
    """Readiness only; no model import, GPU allocation, network or service start."""
    root=Path(engine_root).resolve()
    try:folder=model_path(root)
    except ValueError:folder=None
    available=all(importlib.util.find_spec(package) is not None for package in
                  ('faster_whisper','ctranslate2','av','tokenizers','onnxruntime'))
    cuda=next((root/p for p in ('runtime/asr/cuda','components/asr/cuda')
               if all((root/p/f).is_file() for f in ('cublas64_12.dll','cublasLt64_12.dll','cudart64_12.dll'))),None)
    return {'ready':folder is not None and available,'model':MODEL,'engine':'faster-whisper',
            'model_path':str(folder) if folder else None,'dependency_available':available,
            'cuda_libraries_present':cuda is not None,'device_capability':None,
            'message':('本地模型与运行包文件已就绪；GPU/识别效果需实际推理验证。' if folder and available
                       else '本地语音模型或运行依赖尚未完整准备；不会隐式联网下载。')}


def empty_result(status,duration=0,device=None,compute_type=''):
    return {'status':status,'engine':'faster-whisper','model':MODEL,'device':device,'compute_type':compute_type,
        'language':None,'language_probability':None,'audio_duration':duration,'processed_duration':duration,
        'complete':True,'segments':[],'text':'','uncertain_segments':[],'nonlexical_segments':[],'rejected_segments':[],
        'warnings':['机器识别不保证逐字准确；完整指所选主音轨处理结束。',
                    '未做独立人声/音乐分类；音乐和环境音可能被误识别，no_speech通常仅指模型未输出文字。']}


def _number(value,default):
    if isinstance(value,bool):return default
    try:value=float(value)
    except (ValueError,TypeError):return default
    return value if math.isfinite(value) else default


def recognize(model,audio_path,duration,device,compute_type,emit=None,cancel=None):
    _cancel(cancel)
    iterator,info=model.transcribe(str(audio_path),beam_size=5,vad_filter=False,temperature=0.0,
                                  condition_on_previous_text=False,word_timestamps=False)
    result=empty_result('no_speech',duration,device,compute_type)
    result['language']=getattr(info,'language',None)
    result['language_probability']=_number(getattr(info,'language_probability',None),None)
    segments=[];uncertain=[];nonlexical=[];rejected=[];clipped=False
    # Exhaust the lazy iterator. A failure at any later chunk must propagate.
    for item in iterator:
        _cancel(cancel)
        raw_start=_number(getattr(item,'start',None),None)
        raw_end=_number(getattr(item,'end',None),None)
        text=str(item.text).strip()
        if not text:continue
        logprob=_number(getattr(item,'avg_logprob',None),-99)
        silence=_number(getattr(item,'no_speech_prob',None),1)
        if raw_start is None or raw_end is None or raw_end<=raw_start or raw_start>=duration or raw_end<=0:
            rejected.append({'start':raw_start,'end':raw_end,'text':text,'avg_logprob':logprob,
                'no_speech_prob':silence,'reason':'原始模型时间区间无效或不与所选音轨重叠，未作为speech事实。'})
            continue
        start=max(0,raw_start);end=min(duration,raw_end)
        if start!=raw_start or end!=raw_end:clipped=True
        if not any(character.isalnum() for character in text):
            nonlexical.append({'start':start,'end':end,'text':text,'avg_logprob':logprob,'no_speech_prob':silence,
                'reason':'模型仅输出标点或符号，不作为词汇/口播事实。'})
            _emit(emit,min(99,100*end/duration) if duration else 0,'已记录非词汇输出供审查，继续完整音轨')
            continue
        compression=_number(getattr(item,'compression_ratio',None),0)
        doubtful=logprob < -1.0 or silence > .6 or compression > 2.4
        if doubtful:uncertain.append(len(segments))
        segments.append({'start':start,'end':end,'text':text,'avg_logprob':logprob,
                         'no_speech_prob':silence,'uncertain':doubtful})
        _emit(emit,min(99,100*end/duration) if duration else 0,'正在转写完整音轨，当前位置 '+str(round(end,1))+' 秒')
    _cancel(cancel)
    result.update(status='complete' if segments else 'no_speech',segments=segments,
                  text='\n'.join(s['text'] for s in segments),uncertain_segments=uncertain,
                  nonlexical_segments=nonlexical,rejected_segments=rejected)
    if uncertain:result['warnings'].append('部分片段识别置信度偏低，请结合画面核对品牌、命令与数值。')
    if nonlexical:result['warnings'].append('模型有仅标点/符号的非词汇输出，已保存在nonlexical_segments，不计入口播全文或speech依据。')
    if rejected:result['warnings'].append('模型有无效或音轨外的时间区间，原始输出保存在rejected_segments，未挤到末帧或作为speech依据。')
    if clipped:result['warnings'].append('部分有效模型区间跨越音轨边界，仅保留与真实音轨重叠的时间；边界文字须人工核对。')
    _emit(emit,100,'完整音轨迭代已结束'+('，未输出可用词汇' if not segments else ''))
    return result


def _srt_time(seconds):
    value=max(0,round(seconds*1000));hours,value=divmod(value,3600000);minutes,value=divmod(value,60000);seconds,ms=divmod(value,1000)
    return f'{hours:02}:{minutes:02}:{seconds:02},{ms:03}'


def write_outputs(result,work_dir,cache_hit):
    work_dir=Path(work_dir);work_dir.mkdir(parents=True,exist_ok=True)
    result=dict(result,cache_hit=bool(cache_hit))
    for key,name in (('txt_path','transcript.txt'),('srt_path','transcript.srt'),('json_path','transcript.json')):
        result[key]=str((work_dir/name).resolve())
    Path(result['txt_path']).write_text(result['text'],encoding='utf-8')
    subtitles='\n\n'.join(f"{i+1}\n{_srt_time(s['start'])} --> {_srt_time(s['end'])}\n{s['text']}" for i,s in enumerate(result['segments']))
    Path(result['srt_path']).write_text(subtitles+('\n' if subtitles else ''),encoding='utf-8')
    _atomic_json(Path(result['json_path']),result)
    return result


def _valid_complete(result,duration=None):
    if not isinstance(result,dict) or result.get('complete') is not True or result.get('status') not in ('complete','no_audio','no_speech'):
        raise ValueError('转写未完整结束，不能继续生成运营方案')
    if not isinstance(result.get('segments'),list) or not isinstance(result.get('text'),str):raise ValueError('转写结果结构不完整')
    processed=_number(result.get('processed_duration'),-1);audio=_number(result.get('audio_duration'),-2)
    if processed<0 or audio<0 or abs(processed-audio)>.05 or (duration is not None and abs(audio-duration)>.05):
        raise ValueError('完整音轨处理覆盖不一致')
    if result.get('engine')!='faster-whisper' or result.get('model')!=MODEL:raise ValueError('转写模型标识不一致')
    if result['status']=='complete' and not result['segments']:raise ValueError('有声转写状态缺少段落')
    if result['status'] in ('no_audio','no_speech') and (result['segments'] or result['text']):raise ValueError('无音轨/无识别文字状态不一致')
    if result['status']=='no_audio' and audio!=0:raise ValueError('无音轨状态时长必须为0')
    texts=[];uncertain=[];previous=-1
    for index,segment in enumerate(result['segments']):
        if not isinstance(segment,dict):raise ValueError('转写片段格式无效')
        start=_number(segment.get('start'),-1);end=_number(segment.get('end'),-1)
        if start<0 or end<=start or start>=audio or end>audio+.05 or start<previous:raise ValueError('转写片段时序或范围无效')
        previous=start
        text=segment.get('text')
        if not isinstance(text,str) or not text.strip():raise ValueError('转写片段文字为空')
        texts.append(text)
        if _number(segment.get('avg_logprob'),None) is None or not 0<=_number(segment.get('no_speech_prob'),-1)<=1:
            raise ValueError('转写片段置信字段无效')
        if not isinstance(segment.get('uncertain'),bool):raise ValueError('转写片段置信标记无效')
        if segment['uncertain']:uncertain.append(index)
    if result['text']!='\n'.join(texts):raise ValueError('完整文字与全部转写片段不一致，可能已被截断')
    if result.get('uncertain_segments')!=uncertain:raise ValueError('低置信索引与片段不一致')
    nonlexical=result.get('nonlexical_segments',[])
    if not isinstance(nonlexical,list):raise ValueError('非词汇审查记录须为数组')
    for item in nonlexical:
        if not isinstance(item,dict) or not isinstance(item.get('text'),str) or any(c.isalnum() for c in item['text']):
            raise ValueError('非词汇审查记录结构不一致')
        if not 0<=_number(item.get('start'),-1)<=_number(item.get('end'),-1)<=audio+.05:
            raise ValueError('非词汇记录时间范围无效')
    rejected=result.get('rejected_segments',[])
    if not isinstance(rejected,list) or any(not isinstance(s,dict) or not isinstance(s.get('text'),str) or not isinstance(s.get('reason'),str) for s in rejected):
        raise ValueError('拒绝区间审查记录结构无效')
    if not isinstance(result.get('warnings'),list) or any(not isinstance(w,str) for w in result['warnings']):raise ValueError('转写限制说明结构无效')
    return result


def _digest_json(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')).hexdigest()


def cache_document(result,key,video_hash):
    return {'cache_version':2,'key':key,'video_sha256':video_hash,'settings':SETTINGS_VERSION,
            'result_sha256':_digest_json(result),'result':result}


def read_cache_document(document,key,video_hash):
    if not isinstance(document,dict) or document.get('cache_version')!=2 or document.get('key')!=key or document.get('video_sha256')!=video_hash or document.get('settings')!=SETTINGS_VERSION:
        raise ValueError('缓存来源或版本不匹配')
    result=document.get('result')
    if document.get('result_sha256')!=_digest_json(result):raise ValueError('缓存完整性校验失败')
    return _valid_complete(result)


def _worker_command():
    if getattr(sys,'frozen',False):
        exe=Path(sys.executable).parent/'ContentCtl.exe'
        if not exe.is_file():raise ValueError('缺少同级ContentCtl语音工作进程')
        return [str(exe),'_speech_worker']
    return [sys.executable,'-m','studio.cli','_speech_worker']


def _worker_timeout(duration):
    return max(300,min(14400,duration*30+180))


def run_worker(audio_path,duration,work_dir,device,engine_root,emit=None,cancel=None):
    _cancel(cancel)
    work_dir=Path(work_dir);folder=work_dir/('worker-'+device+'-'+str(time.time_ns()));folder.mkdir(parents=True,exist_ok=True)
    request,events,result,marker=(folder/name for name in ('request.json','events.jsonl','result.json','cancel'))
    # Attempt dirs are unique per invocation; never consume a stale prior result.
    result.unlink(missing_ok=True);events.unlink(missing_ok=True);marker.unlink(missing_ok=True)
    _atomic_json(request,{'audio_path':str(Path(audio_path).resolve()),'audio_duration':duration,
        'work_dir':str(work_dir.resolve()),'engine_root':str(Path(engine_root).resolve()),'device':device,'cancel_path':str(marker)})
    process=subprocess.Popen(_worker_command()+['--request',str(request),'--events',str(events),'--result',str(result)],
        cwd=str(Path(__file__).resolve().parent.parent),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    deadline=time.monotonic()+_worker_timeout(duration);offset=0
    def drain():
        nonlocal offset
        if not events.exists():return
        with events.open(encoding='utf-8') as source:
            source.seek(offset)
            while True:
                before=source.tell();line=source.readline()
                if not line or not line.endswith('\n'):offset=before;break
                offset=source.tell()
                try:event=json.loads(line)
                except ValueError:continue
                if emit:emit({k:event[k] for k in ('stage','progress','message') if k in event})
    try:
        while process.poll() is None:
            _cancel(cancel);drain()
            if time.monotonic()>deadline:raise ValueError('语音工作进程超时，未生成完整结果')
            time.sleep(.2)
        _cancel(cancel);drain()
        if not result.is_file():raise ValueError('语音工作进程未成功结束，退出码 '+str(process.returncode))
        data=json.loads(result.read_text(encoding='utf-8'))
        if 'error' in data:raise ValueError('语音引擎失败：'+str(data['error'].get('type','unknown')))
        if process.returncode!=0:raise ValueError('语音工作进程异常退出，未采纳结果')
        return _valid_complete(data,duration)
    finally:
        if process.poll() is None:
            marker.touch();process.terminate()
            try:process.wait(timeout=3)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=3)


def _video_hash(path,cancel):
    digest=hashlib.sha256()
    with path.open('rb') as source:
        while data:=source.read(4*1024*1024):_cancel(cancel);digest.update(data)
    return digest.hexdigest()


def transcribe_video(asset,work_dir,engine_root,emit=None,cancel=None):
    _cancel(cancel);work_dir=Path(work_dir).resolve();work_dir.mkdir(parents=True,exist_ok=True)
    root=Path(engine_root).resolve();video=Path(asset.get('path','')).resolve()
    if not video.is_file():raise ValueError('待转写视频不存在')
    source_stamp=(video.stat().st_size,video.stat().st_mtime_ns)
    identity=_video_hash(video,cancel)
    if asset.get('sha256') and asset['sha256']!=identity:raise ValueError('视频内容已变化，未采用旧素材记录')
    def unchanged():
        _cancel(cancel)
        if not video.is_file() or (video.stat().st_size,video.stat().st_mtime_ns)!=source_stamp:
            raise ValueError('转写期间视频已变化，未保存成功结果或缓存')
    unchanged()
    try:
        model=model_path(root)
        stamp=[(f.name,f.stat().st_size,f.stat().st_mtime_ns) for f in model.iterdir() if f.is_file()]
    except ValueError:model=None;stamp=[]
    versions={}
    for package in ('faster-whisper','ctranslate2'):
        try:versions[package]=version(package)
        except PackageNotFoundError:versions[package]='unavailable'
    key=hashlib.sha256(json.dumps([identity,MODEL,SETTINGS_VERSION,sorted(stamp),versions],sort_keys=True).encode()).hexdigest()
    cache=root/'state/asr_cache'/(key+'.json')
    if cache.is_file():
        try:cached=read_cache_document(json.loads(cache.read_text(encoding='utf-8')),key,identity)
        except (ValueError,TypeError):cached=None
        if cached is not None:
            unchanged()
            _emit(emit,100,'使用已完成全音轨转写缓存')
            return write_outputs(cached,work_dir,True)
    _emit(emit,0,'正在检查所选主音轨',stage='audio')
    track=probe_audio(video,root,cancel)
    if track is None:
        result=empty_result('no_audio')
        result['warnings'].append('视频没有音轨，未进行语音识别。')
        _emit(emit,100,'已确认视频无音轨',stage='audio')
    else:
        audio,duration=extract_audio(video,track,work_dir,root,cancel)
        _emit(emit,0,'完整主音轨已解码，准备本地语音识别',stage='audio')
        if is_digital_silence(audio,cancel):
            result=empty_result('no_speech',duration)
            result['warnings']=['完整解码PCM全为数字零，无可识别人声；未启动模型。']
            _emit(emit,100,'完整PCM已扫描，确认为数字静音')
        else:
            if model is None:raise ValueError('本地large-v3-turbo模型尚未完整安装，未联网下载')
            try:result=run_worker(audio,duration,work_dir,'cuda',root,emit,cancel)
            except GenerationCancelled:raise
            except (ValueError,OSError):
                _cancel(cancel)
                _emit(emit,0,'GPU识别未完成，唯一一次回退CPU int8；重新处理完整音轨')
                result=run_worker(audio,duration,work_dir,'cpu',root,emit,cancel)
                result['warnings'].append('GPU尝试失败，已在独立CPU int8进程重新完整转写。')
        _valid_complete(result,duration)
        offset=_number(track.get('audio_start_time'),0)-_number(track.get('format_start_time'),0)
        result['audio_alignment']={'timeline':'container_relative_ffmpeg_input_seek',
            'format_start_time':track.get('format_start_time',0),'audio_start_time':track.get('audio_start_time',0),
            'video_start_time':track.get('video_start_time'),'leading_silence_seconds':max(0,round(offset*16000)/16000)}
        result['warnings'].extend(track.get('alignment_warnings',[]))
        if offset>1/16000:result['warnings'].append('完整解码音轨前补齐 '+str(round(offset,6))+' 秒对齐静音；audio_duration/processed_duration包含该静音，与视频抽帧时间轴一致。')
    unchanged()
    _valid_complete(result)
    cache_data={k:v for k,v in result.items() if k not in ('txt_path','srt_path','json_path','cache_hit')}
    _atomic_json(cache,cache_document(cache_data,key,identity))
    return write_outputs(result,work_dir,False)


def worker_main(request_path,events_path,result_path):
    """CLI entry: isolated model import/inference. Never downloads weights."""
    request=json.loads(Path(request_path).read_text(encoding='utf-8'))
    marker=Path(request['cancel_path']);cancel=lambda:marker.exists()
    def emit(event):
        with Path(events_path).open('a',encoding='utf-8') as target:target.write(json.dumps(event,ensure_ascii=False)+'\n')
    handles=[];libraries=[]
    try:
        root=Path(request['engine_root']).resolve();work=Path(request['work_dir']).resolve();audio=Path(request['audio_path']).resolve()
        if not audio.is_relative_to(work) or not audio.is_file():raise ValueError('音轨必须位于本任务工作目录')
        _cancel(cancel)
        for relative in ('runtime/asr/cuda','components/asr/cuda'):
            dll=root/relative
            if os.name=='nt' and dll.is_dir():
                handles.append(os.add_dll_directory(str(dll)))
                if request.get('device')=='cuda':
                    # CT2 loads vendor libraries dynamically. Preload our exact
                    # files so it cannot accidentally pick another app's CUDA.
                    import ctypes
                    for name in ('cudart64_12.dll','cublasLt64_12.dll','cublas64_12.dll'):
                        file=dll/name
                        if file.is_file():libraries.append(ctypes.WinDLL(str(file)))
                break
        # DLL search is local to this worker; never set the system or process PATH.
        from faster_whisper import WhisperModel
        device=request.get('device','cuda')
        if device not in ('cuda','cpu'):raise ValueError('无效语音设备')
        compute='float16' if device=='cuda' else 'int8'
        _emit(emit,0,'加载本地 '+MODEL+'，设备 '+device)
        model=WhisperModel(str(model_path(root)),device=device,compute_type=compute,local_files_only=True,
                           cpu_threads=max(1,min(8,os.cpu_count() or 1)),num_workers=1)
        duration=float(request['audio_duration'])
        if not math.isfinite(duration) or duration<0:raise ValueError('音轨时长无效')
        data=recognize(model,audio,duration,device,compute,emit,cancel)
        _atomic_json(Path(result_path),data)
        return 0
    except GenerationCancelled:
        _atomic_json(Path(result_path),{'error':{'type':'GenerationCancelled','message':'转写已取消'}});return 2
    except Exception as exc:
        _atomic_json(Path(result_path),{'error':{'type':type(exc).__name__,'message':str(exc)[:800]}});return 2
    finally:
        for handle in handles:handle.close()
