import json
import os.path
from pathlib import Path

from langfuse import observe, get_client

from pipeline.base import VideoPipelineStage
from pipeline.context import PipelineContext
from domain.movie import Movie, Video
from models.enums import StageStatus, PiplinePhase, TaskType
from models.results import ProcessResult, ChatResult
from services.pipeline.manifest import SQLiteManifest
from services.translation.orchestrator import TranslateOrchestrator
from services.translation.provider import Provider, OpenaiProvider
from utils.logger import setup_logger

logger = setup_logger("translator")


class CorrectStage(VideoPipelineStage):
    """字幕校正流水线阶段。

    负责对视频字幕进行校正处理。
    Attributes:
        check_provider (Provider): 用于校正完整性的服务。
    """

    def __init__(self, check_provider: Provider):
        self.check_provider = check_provider

    def name(self):
        """获取阶段名称。

        Returns:
            str: 阶段名称 "correction"。
        """
        return "correction"

    @observe
    def _quality_check(self, text: str, context: PipelineContext) -> bool:
        """
            使用低成本的LLM对字幕质量进行检查。
            Args:
                text (str): 待检查的字幕文本。
                context(PipelineContext): 流水线执行上下文。
            Returns:
                bool: 如果字幕质量合格返回True，否则返回False。
        """
        system_prompt = """You are an ultra-fast subtitle quality check API. Your task is to determine if a subtitle file is structurally broken based on a small sample. Your response must be immediate and only in the specified JSON format.

**Analysis Criteria (Based ONLY on the sample):**
1.  **Structural Damage:** Is the file completely missing timestamps (`-->`) or is the sequence number logic broken?
2.  **Unusable Garbage:** Is the text composed of random characters (e.g., "j@#f!d$"), encoding errors (e.g., ""), or ONLY consists of meaningless, non-dialogue placeholders like "Music" or "Opening" in the entire sample?

**IMPORTANT: Do NOT fail a file for these reasons (These are ACCEPTABLE):**
- **Natural Conversation:** The presence of common conversational fillers/interjections in Japanese (e.g., 「えっと」「うん」「あの」「はい」「うーん」) is NORMAL and indicates a good transcription. DO NOT count these as errors.
- **Time Gaps:** Large gaps in timestamps between subtitle entries are NORMAL and simply mean there is no dialogue in that part of the video.
- **Advertisements:** The presence of ads at the beginning or end is acceptable.

**Output Format (Your entire response MUST be ONLY this valid JSON object):**
- If the sample appears usable for further processing: `{"qualified": true}`
- If the sample is structurally broken or pure garbage: `{"qualified": false, "reason": "A very brief, 10-word max explanation."}`
"""
        langfuse = get_client()
        langfuse.update_current_trace(session_id=context.langfuse_session_id,
                                      tags=["quality_check", "subtitle", context.movie_code])
        user_query = {
            "info": "这是一个成人影片的视频字幕",
            "text": text
        }
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": str(user_query)}
        ]
        logger.info("Checking subtitle quality with low-cost LLM...")
        result: ChatResult = self.check_provider.chat(messages, temperature=0.0,
                                                      response_format={"type": "json_object"})
        if result.success:
            logger.info(f"Subtitle quality check completed. Spend {result.time_taken / 1000.0} seconds.")
            try:
                result_json_object = json.loads(result.content)
                logger.info(f"Subtitle quality check completed. Response is {result_json_object}")
                return result_json_object.get("qualified", True)  # 乐观估计，默认合格
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse quality check result as JSON: {e}")
                return True
        else:
            logger.error("Failed to check subtitle quality")
            return True

    def should_execute(self, video, context: PipelineContext):
        """判断是否应该执行校正阶段。

        Args:
            video (Video): 待检查的视频对象。
            context(PipelineContext): 流水线执行上下文。
        Returns:
            bool: 如果校正阶段未成功完成则返回True。
        """
        # 检查当前阶段状态
        status = video.status.get(PiplinePhase.CORRECT_SUBTITLE, StageStatus.PENDING)
        return status != StageStatus.SUCCESS

    @observe
    def execute(self, movie: Movie, video: Video, context: PipelineContext):
        """执行字幕校正处理。

        读取原始字幕文件，使用校正服务进行校正，并将结果保存到输出文件。

        Args:
            movie (Movie): 视频所属的电影对象。
            video (Video): 待处理的视频对象。
            context (PipelineContext): 流水线执行上下文。

        """
        langfuse = get_client()
        langfuse.update_current_trace(session_id=context.langfuse_session_id, tags=["correct", "subtitle", movie.code])
        srt_raw = Path(video.by_products[PiplinePhase.TRANSCRIBE_AUDIO]).read_text(encoding="utf-8")
        result: ProcessResult = context.translator.correct_subtitle(
            text=srt_raw,
            metadata=movie.metadata.to_serializable_dict(),
            terms=movie.terms
        )
        if result.success:
            corrected_srt = result.content
            corrected_path = os.path.join(context.output_dir, movie.code, video.filename + ".corrected.srt")
            video.by_products[PiplinePhase.CORRECT_SUBTITLE] = corrected_path
            path = Path(corrected_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.touch(exist_ok=True)
            path.write_text(corrected_srt, encoding="utf-8")
            logger.info(f"Successfully corrected subtitle, saved to {corrected_path}")
            existed_terms = {term["japanese"] for term in movie.terms}
            for term in result.terms:
                if term["japanese"] not in existed_terms:
                    movie.terms.append(term)
                    existed_terms.add(term["japanese"])
            video.status[PiplinePhase.CORRECT_SUBTITLE] = StageStatus.SUCCESS
        else:
            logger.error(f"Failed to correct subtitle for video {video.filename}")
            video.status[PiplinePhase.CORRECT_SUBTITLE] = StageStatus.FAILED
        return


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    manifest = SQLiteManifest()
    mock_movie = manifest.get_movie("DDT-185")
    mock_video = Video(
        sha256="dummyhash",
        filename="example_video",
        suffix=".mp4",
        absolute_path="/path/to/example_video.mp4",
        by_products={
            PiplinePhase.TRANSCRIBE_AUDIO: os.path.join(os.getcwd(), "output",
                                                        "[Dogma] あれから10年 秘儀伝授 男のバイブルVOL．1 完全潮吹き入門(ddt-185.srt")
        },
        status={
            PiplinePhase.TRANSCRIBE_AUDIO: StageStatus.SUCCESS
        }
    )
    mock_movie.videos = [mock_video]

    check_provider = OpenaiProvider(api_key=os.getenv("OPENROUTER_API_KEY"), base_url=os.getenv("OPENROUTER_BASE_URL"),
                                    model="deepseek/deepseek-v3.1-terminus")
    correct_provider = OpenaiProvider(api_key=os.getenv("OPENROUTER_API_KEY"),
                                      base_url=os.getenv("OPENROUTER_BASE_URL"), model="google/gemini-2.5-pro")
    translator = TranslateOrchestrator(
        {
            TaskType.CORRECT_SUBTITLE: [correct_provider],
        }
    )
    context = PipelineContext(translator=translator, manifest=manifest, movie_code="DDT-185",
                              langfuse_session_id="test-session-ddt-185", )
    corrector = CorrectStage(check_provider)
    if corrector.should_execute(mock_video, context):
        corrector.execute(mock_movie, mock_video, context)
        context.manifest.update_movie(mock_movie)
    else:
        logger.info("No need to execute correction stage.")
