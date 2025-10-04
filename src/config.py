import logging
import os

from dotenv import load_dotenv

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Загружаем переменные окружения
load_dotenv()


class Config:
    def __init__(self):
        self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
        available_models = os.getenv(
            "OPENAI_AVAILABLE_MODELS",
            "gpt-3.5-turbo,gpt-4o-mini,gpt-4o",
        )
        self.AVAILABLE_MODELS = [
            model.strip() for model in available_models.split(",") if model.strip()
        ]
        default_model = os.getenv("OPENAI_MODEL_NAME", "gpt-3.5-turbo")
        self.MODEL_NAME = (
            default_model
            if default_model in self.AVAILABLE_MODELS
            else self.AVAILABLE_MODELS[0]
        )
        self.DEFAULT_TEMPERATURE = float(os.getenv("OPENAI_TEMPERATURE", "0.7"))

        # Отладочная информация
        if not self.OPENAI_API_KEY:
            logger.error("OPENAI_API_KEY не найден в переменных окружения!")
        elif self.OPENAI_API_KEY.startswith("your_ope"):
            logger.error("OPENAI_API_KEY содержит placeholder значение!")
        else:
            logger.info(
                "OPENAI_API_KEY загружен: %s...",
                self.OPENAI_API_KEY[:8],
            )


def get_config():
    return Config()
