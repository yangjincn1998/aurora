from domain.movie import Movie
from pipeline.context import PipelineContext
from pipeline.scrape import ScrapeStage
from services.pipeline.database_manager import DatabaseManager
from services.translation.orchestrator import TranslateOrchestrator
from services.web_request.javbus_web_service import JavBusWebService
import dotenv

dotenv.load_dotenv()

scraper = ScrapeStage([JavBusWebService()])
database_manager = DatabaseManager()
translator = TranslateOrchestrator.from_config_yaml("config.yml")
pipeline_context = PipelineContext(database_manager, translator, "CJOD", "test")


for i in range(100, 110):
    pipeline_context.begin_transaction()
    movie = Movie(code=f"CJOD-{i}")
    scraper.execute(movie, pipeline_context)
    pipeline_context.update_movie(movie)
    pipeline_context.commit_transaction()
