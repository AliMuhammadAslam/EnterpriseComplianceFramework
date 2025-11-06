from pydantic import BaseModel
from litellm import completion
from dotenv import load_dotenv
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()


class Executor:
    def __init__(self, modelName="gpt-4o", agentRole=""):
        self.ModelName = ""
        self.Role = agentRole + "\n"
        if modelName.lower()[0:3] == "gpt":
            self.ModelName = "openai/" + modelName

    def get_response(self, message: str):
        logger.info(f"The model used is: {self.ModelName}")
        try:
            response = completion(
                model=self.ModelName,
                messages=[
                    {
                        "content": message,
                        "role": "user",
                    }
                ],
            )
        except Exception as e:
            logger.error(f"Error in executor: {e}")
            return ""

        return response

    def execute(self, task: str, context: dict = None):

        pass
