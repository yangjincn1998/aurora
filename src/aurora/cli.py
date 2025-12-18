import os

import dotenv

from aurora.pipeline._pipeline import Pipeline
from aurora.pipeline.bilingual_subtitle import BilingualSubtitleStage
from aurora.pipeline.correct import CorrectStage
from aurora.pipeline.denoise_audio import DenoiseAudioStage
from aurora.pipeline.extract_audio import ExtractAudioStage
from aurora.pipeline.scrape import ScrapeStage
from aurora.pipeline.transcribe_audio import TranscribeAudioStage
from aurora.pipeline.translate import TranslateStage
from aurora.services.code_extract.extractor import CodeExtractor
from aurora.services.denoise.denoiser import Denoiser
from aurora.services.pipeline.database_manager import DatabaseManager
from aurora.services.transcription.transcription_service import TranscriptionService
from aurora.services.translation.orchestrator import TranslateOrchestrator
from aurora.services.translation.provider import OpenaiProvider
from aurora.services.web_request.javbus_web_service import JavBusWebService

dotenv.load_dotenv()


def main():
    denoiser = Denoiser.from_yaml_config("config.yaml")
    transcriber = TranscriptionService.from_yaml("../../config.yaml")
    translator = TranslateOrchestrator.from_config_yaml("../../config.yaml")

    # 创建降噪器实例
    denoise_config = {
        "type": "noisereduce",
        "segment_duration": 30,
        "prop_decrease": 0.8,
        "stationary": True,
        "noise_sample_duration": 1.0,
    }
    denoiser = Denoiser.from_config(denoise_config)

    pipeline = Pipeline(
        [ScrapeStage([JavBusWebService()])],
        [
            ExtractAudioStage(),
            DenoiseAudioStage(denoiser),
            TranscribeAudioStage(
                OpenaiProvider(
                    os.getenv("OPENROUTER_API_KEY"),
                    os.getenv("OPENROUTER_BASE_URL"),
                    "z-ai/glm-4.6",
                )
            ),
            CorrectStage(),
            TranslateStage(),
            BilingualSubtitleStage(),
        ],
        CodeExtractor([JavBusWebService()]),
        DatabaseManager(),
        translator,
    )
    pipeline.run(r"D:\4. Collections\6.Adult Videos\raw")


if __name__ == "__main__":
    main()
