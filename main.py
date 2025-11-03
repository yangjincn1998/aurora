import os

import dotenv

from pipeline._pipeline import Pipeline
from pipeline.bilingual_subtitle import BilingualSubtitleStage
from pipeline.correct import CorrectStage
from pipeline.denoise_audio import DenoiseAudioStage
from pipeline.extract_audio import ExtractAudioStage
from pipeline.scrape import ScrapeStage
from pipeline.transcribe_audio import TranscribeAudioStage
from pipeline.translate import TranslateStage
from services.code_extract.extractor import CodeExtractor
from services.denoise.denoiser import Denoiser
from services.pipeline.database_manager import SQLiteDatabaseManager
from services.transcription.transcription_service import TranscriptionService
from services.translation.orchestrator import TranslateOrchestrator
from services.translation.provider import OpenaiProvider
from services.web_request.javbus_web_service import JavBusWebService

dotenv.load_dotenv()

denoiser = Denoiser.from_yaml_config("config.yaml")
transcriber = TranscriptionService.from_yaml("config.yml")
translator = TranslateOrchestrator.from_config_yaml("config.yml")

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
        CorrectStage(
            OpenaiProvider(
                os.getenv("OPENROUTER_API_KEY"),
                os.getenv("OPENROUTER_BASE_URL"),
                "z-ai/glm-4.6",
            )
        ),
        TranslateStage(),
        BilingualSubtitleStage(),
    ],
    CodeExtractor([JavBusWebService()]),
    SQLiteDatabaseManager(),
    translator,
)

pipeline.run(r"D:\4. Collections\6.Adult Videos\raw")
