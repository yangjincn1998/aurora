import os.path
import threading
from pathlib import Path
from audio_extractor import FatalError, extract_audio_worker
from config import VIDEO_SOURCE_DIRECTORY, AUDIO_DIR, SCH_SUB_DIR, JAP_SUB_DIR, METADATA_PATH, BILINGUAL_SUB_DIR
from exceptions import IgnorableError
from logging_config import setup_logging
from scanner import scan_and_make_json
from movie_crawler import process_movie_metadata
from subtitle_generator import generate_subtitle_worker
from transcriber import transcribe_audio_worker
from text_translator import translate_srt_worker
import json

setup_logging()
gpu_lock = threading.Lock()
shared_status = {'transcription_service':'assemblyai'}

def linear_processor():
    try:
        scan_and_make_json()
    except FatalError as e:
        raise e
    meta_txt = METADATA_PATH.read_text(encoding='utf-8')
    metadata = json.loads(meta_txt)
    for av_code in metadata:
        try:
            process_movie_metadata(av_code)
        except FatalError as e:
            continue
        except IgnorableError as e:
            pass
        for segment_id, segment_status in metadata[av_code]['segments'].items():
            if segment_status.get('deleted', False):
                continue
            try:
                #构造所有可能的中间文件
                full_path = segment_status['full_path']

                stem = Path(segment_id).stem
                audio_path = AUDIO_DIR/(stem + '.mp3')
                jap_srt_path = JAP_SUB_DIR / (stem + ".srt")
                sch_srt_path = SCH_SUB_DIR / (stem + ".srt")
                bilingual_srt_path = BILINGUAL_SUB_DIR / f"{stem}.srt"
                bilingual_ass_path = BILINGUAL_SUB_DIR / f"{stem}.ass"
                if not audio_path.exists() and not jap_srt_path.exists() and not sch_srt_path.exists() and (not bilingual_srt_path.exists() or not bilingual_srt_path):
                    extract_audio_worker(av_code, segment_id, full_path, force=False)
                if not jap_srt_path.exists() and not sch_srt_path.exists() and (not bilingual_srt_path.exists() or not bilingual_ass_path.exists()):
                    transcribe_audio_worker(av_code, segment_id, str(audio_path), gpu_lock, shared_status, force=True)
                if not sch_srt_path.exists() and (not bilingual_srt_path.exists() or not bilingual_ass_path.exists()):
                    translate_srt_worker(av_code, segment_id, str(jap_srt_path), str(METADATA_PATH))
                if not bilingual_srt_path.exists() or not bilingual_ass_path.exists():
                    generate_subtitle_worker(av_code, segment_id)
            except FatalError as e:
                continue
            except IgnorableError as e:
                pass
if __name__ == '__main__':
    linear_processor()
