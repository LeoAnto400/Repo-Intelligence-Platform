from abc import ABC, abstractmethod
from typing import Any, Dict

class BaseAgent(ABC):
    """
    Abstract Base Class defining the standard interface for all agents 
    within the intelligence assistant system.
    """
    
    @abstractmethod
    async def process(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Processes incoming payload data/queries and returns structured results.
        
        Args:
            payload: Parameters and context for the agent task execution.
            
        Returns:
            Dict containing agent's outputs, metadata, or status code.
        """
        pass
