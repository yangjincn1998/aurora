from abc import ABC, abstractmethod

class PiplineStage(ABC):
    @property
    @abstractmethod
    def name(self):
        pass
    @abstractmethod
    def execute(self, entity: Entity) -> Entity:
        pass