from pydantic import BaseModel
from litellm import completion
from dotenv import load_dotenv
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()


class Planner:

    def __init__(self, modelName="gpt-4o", agentRole=""):
        self.ModelName = ""
        self.Role = (
            agentRole + "\n"
        )  # added new line for just some formatting in the prompt
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
            logger.error(f"Error in planner: {e}")
            return ""

        return response

    def plan(self, goal: str, context: dict = None):

        pass

    def breakDownTask(self, task: str):

        pass
