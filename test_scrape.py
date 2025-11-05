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
pipeline_context = PipelineContext(database_manager, translator, "bban", "test")


for i in range(371, 381):
    pipeline_context.begin_transaction()
    movie = Movie(code=f"BBAn-{i}")
    scraper.execute(movie, pipeline_context)
    pipeline_context.update_movie_for_test(movie)
    pipeline_context.commit_transaction()
