import os
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))

# 获取.env文件中的DEEPSEEK_API_KEY值，如果没有获取到，默认值为”“
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY',"")
DEEPSEEK_BASE_URL = os.getenv('DEEPSEEK_BASE_URL',"https://api.deepseek.com")
DEEPSEEK_MODEL = os.getenv('DEEPSEEK_MODEL',"")
DEEPSEEK_TEMPERATURE = float(os.getenv('DEEPSEEK_TEMPERATURE', "0.7"))
DEEPSEEK_MAX_TOKENS = int(os.getenv('DEEPSEEK_MAX_TOKENS', "2048"))

CHUNK_SIZE = int(os.getenv('CHUNK_SIZE', "400"))
CHUNK_OVERLAP = int(os.getenv('CHUNK_OVERLAP', "100"))
RETRIEVAL_TOP_K = int(os.getenv('RETRIEVAL_TOP_K', "4"))

# 设置数据存放地址，规定绝对路径为当前文件夹下的data文件夹（需要手动创建data文件夹，同时在data文件夹中创建documents文件夹用于存放数据）
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
# 直接获取data文件夹下的documents文件夹路径
DOCUMENTS_DIR = os.path.join(DATA_DIR, 'documents')

# 系统创建自动创建文件夹
os.makedirs(DOCUMENTS_DIR, exist_ok=True)