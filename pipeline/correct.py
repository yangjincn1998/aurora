import json
import os.path
from pathlib import Path

from base import VideoPipelineStage
from domain.movie import Movie, Video, Metadata
from domain.subtitle import BilingualText, BilingualList
from models.enums import StageStatus, PiplinePhase, TaskType
from models.results import ProcessResult, ChatResult
from services.translation.orchestrator import TranslateOrchestrator
from services.translation.provider import Provider, OpenaiProvider
from utils.logger import setup_logger

logger = setup_logger("translator")


class CorrectStage(VideoPipelineStage):
    """字幕校正流水线阶段。

    负责对视频字幕进行校正处理。
    Attributes:
        translator (TranslateOrchestrator): 翻译服务协调器。
    """

    def __init__(self, translator: TranslateOrchestrator, check_provider: Provider):
        self.translator = translator
        self.check_provider = check_provider

    @staticmethod
    def name():
        """获取阶段名称。

        Returns:
            str: 阶段名称 "correction"。
        """
        return "correction"

    def _quality_check(self, text: str) -> bool:
        """
            使用低成本的LLM对字幕质量进行检查。
            Args:
                text (str): 待检查的字幕文本。
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

    def should_execute(self, video):
        """判断是否应该执行校正阶段。

        Args:
            video (Video): 待检查的视频对象。

        Returns:
            bool: 如果校正阶段未成功完成则返回True。
        """
        if not video.status.get(PiplinePhase.CORRECT_SUBTITLE, StageStatus.PENDING) != StageStatus.SUCCESS:
            return False
        else:
            srt = Path(video.by_products[PiplinePhase.TRANSCRIBE_AUDIO]).read_text(encoding="utf-8")
            return self._quality_check(srt)

    def execute(self, movie: Movie, video: Video):
        """执行字幕校正处理。

        读取原始字幕文件，使用校正服务进行校正，并将结果保存到输出文件。

        Args:
            movie (Movie): 视频所属的电影对象。
            video (Video): 待处理的视频对象。

        """
        srt_raw = Path(video.by_products[PiplinePhase.TRANSCRIBE_AUDIO]).read_text(encoding="utf-8")
        result: ProcessResult = self.translator.correct_subtitle(
            text=srt_raw,
            metadata=movie.metadata.to_serializable_dict(),
            terms=movie.terms
        )
        if result.success:
            corrected_srt = result.content
            corrected_path = os.path.join(str(Path(__file__).parent.parent), "output", video.filename + "_corrected.srt")
            video.by_products[PiplinePhase.CORRECT_SUBTITLE] = corrected_srt
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
    Mock_Video = Video(
        sha256="dummyhash",
        filename="example_video",
        suffix=".mp4",
        absolute_path="/path/to/example_video.mp4",
        by_products={
            PiplinePhase.TRANSCRIBE_AUDIO: r"D:\4. Collections\6.Adult Videos\PythonProject\test_mode\pipline_correct\BBAN-217  2.srt"
        },
        status={
            PiplinePhase.TRANSCRIBE_AUDIO: StageStatus.SUCCESS
        }
    )
    Mock_Movie = Movie(
        code="BBAN-217",
        metadata=Metadata(
            title=BilingualText(
                original="BBAN-217 飲尿・浴尿レズビアン ～相手の体液全てを味わい尽くしまみれる2人～",
                translated="BBAN-217 饮尿·浴尿女同性恋 ～尽情品尝对方所有体液的两人～"
            ),
            release_date="2019-02-01",
            director=None,
            studio=BilingualText(
                original="ビビアン",
                translated="Vivian"
            ),
            synopsis=None,
            categories=BilingualList(
                original=["レズビアン", "飲尿", "浴尿"],
                translated=["女同性恋", "饮尿", "浴尿"]
            ),
            actresses=[
                BilingualText(original="宮崎あや ", translated="宫崎绫"),
                BilingualText(original="七海ゆあ ", translated="七海由亚")
            ]
        ),
        videos=[Mock_Video]
    )

    check_provider = OpenaiProvider(api_key=os.getenv("openrouter_api_key"), base_url=os.getenv("openrouter_base_url"),
                                    model="google/gemini-2.0-flash-001")
    correct_provider = OpenaiProvider(api_key=os.getenv("openrouter_api_key"),
                                      base_url=os.getenv("openrouter_base_url"), model="google/gemini-2.5-pro")
    translator = TranslateOrchestrator(
        {
            TaskType.CORRECT_SUBTITLE: [correct_provider],
        }
    )
    corrector = CorrectStage(translator, check_provider)
    if corrector.should_execute(Mock_Video):
        corrector.execute(Mock_Movie, Mock_Video)
        print(Mock_Video)
    else:
        logger.info("No need to execute correction stage.")
