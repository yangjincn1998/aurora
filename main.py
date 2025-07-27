from dotenv import load_dotenv
import logging
import os

load_dotenv()
VIDEO_DIRECTORY=os.getenv('VIDEO_DIRECTORY')
AUDIO_DIRECTORY=os.getenv('AUDIO_DIRECTORY')
JAPSUB_DIRECTORY=os.getenv('JAPSUB_DIRECTORY')
SCHSUB_DIRECTORY=os.getenv('SCHSUB_DIRECTORY')
SCH_JP_DIRECTORY=os.getenv('SCH_JP_DIRECTORY')  
DEEPSEEK_API_KEY=os.getenv('DEEPSEEK_API_KEY')
DEEPSEEK_API_KEY1=os.getenv('DEEPSEEK_API_KEY1')
GEMINI_API_KEY=os.getenv('GEMINI_API_KEY')
GOOGLE_API_KEY=os.getenv('GOOGLE_API_KEY')
ASSEMBLYAI_API_KEY=os.getenv('ASSEMBLYAI_API_KEY')
NO_PROXY=os.getenv('NO_PROXY')
OPENAI_API_KEY=os.getenv('OPENAI_API_KEY')
HTTP_PROXY=os.getenv('HTTP_PROXY')
HTTPS_PROXY=os.getenv('HTTPS_PROXY')

LOG_DIR = 'logs'
os.makedirs(LOG_DIR, exist_ok=True)
logger = logging.getLogger()
logger.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s')
info_handler = logging.FileHandler(os.path.join(LOG_DIR, 'info.log'), encoding='utf-8')
info_handler.setLevel(logging.INFO)
info_handler.setFormatter(formatter)
logger.addHandler(info_handler)
error_handler = logging.FileHandler(os.path.join(LOG_DIR, 'error.log'), encoding='utf-8')
error_handler.setLevel(logging.ERROR)
error_handler.setFormatter(formatter)
logger.addHandler(error_handler)
critical_handler = logging.FileHandler(os.path.join(LOG_DIR, 'critical.log'), encoding='utf-8')
critical_handler.setLevel(logging.CRITICAL)
critical_handler.setFormatter(formatter)
logger.addHandler(critical_handler)
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)















class FatalError(Exception):
    pass
class IgnorableError(Exception):
    pass