from sqlalchemy import create_engine
from aurora.orms.models import Base, Video
from pathlib import Path
from aurora.services.scanner.filesystem_scanner import LibraryScanner
from aurora_scraper.extractor.extractor import VideoInfoExtractor
from aurora_scraper.web_requestor.jav_bus import JavBusClient
import sqlalchemy
from sqlalchemy.orm import Session

sqlite_path = Path(__file__).parent.parent / "sqlite.db"
engine = create_engine(
    f"sqlite:///{sqlite_path.absolute()}",
    connect_args={"check_same_thread": False},
    poolclass=sqlalchemy.pool.StaticPool,
)


Base.metadata.create_all(engine)
session = Session(engine)

extractor = VideoInfoExtractor([JavBusClient()])
scanner = LibraryScanner(session, extractor)
scanner.scan_directory(Path(r"E:\Videos\Adult Videos\raw"))
