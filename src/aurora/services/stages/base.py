from abc import ABC, abstractmethod

from sqlalchemy.orm import Session

from aurora.orms.models import Video, Movie


class PipelineStage(ABC):
    @property
    @abstractmethod
    def name(self):
        pass

    def execute(self, entity: Video | Movie, session: Session):
        pass
