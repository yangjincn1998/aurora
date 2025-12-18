import dotenv

from aurora.domain.movie import Movie
from aurora.pipeline.context import PipelineContext
from aurora.pipeline.scrape import ScrapeStage
from aurora.services.pipeline.database_manager import DatabaseManager
from aurora.services.translation.orchestrator import TranslateOrchestrator
from aurora.services.web_request.javbus_web_service import JavBusWebService

dotenv.load_dotenv()

scraper = ScrapeStage([JavBusWebService()])
database_manager = DatabaseManager()
translator = TranslateOrchestrator.from_config_yaml("../config.yaml")
pipeline_context = PipelineContext(database_manager, translator, "bban", "tests")


for i in range(371, 381):
    pipeline_context.begin_transaction()
    movie = Movie(code=f"BBAN-{i}")
    scraper.execute(movie, pipeline_context)
    pipeline_context.update_movie_for_test(movie)
    pipeline_context.commit_transaction()
