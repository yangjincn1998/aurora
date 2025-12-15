from dataclasses import dataclass

from sqlalchemy.orm import Session


@dataclass(frozen=True)
class PipelineContext:
    session: Session
