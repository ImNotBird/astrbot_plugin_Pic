import os
import asyncio
import aiofiles
import aiohttp
import random
import uuid
import mimetypes
from typing import Optional
from astrbot.api import logger
from astrbot.api.star import Context, Star, register
from astrbot.api.event import AstrMessageEvent, MessageEventResult, filter
from astrbot.api.event.filter import EventMessageType
from astrbot.api.message_components import Plain, Image 
from astrbot.api.tools import StarTools

# 全局文件写锁，防止并发写入冲突
file_lock = asyncio.Lock()

# 常用图片 API 地址
IMAGE_API_URLS = [
    "https://t.alcy.cc/ysz",
    "https://t.alcy.cc/moez",
    "https://t.alcy.cc/ycy",
    "https://t.alcy.cc/moe",
    "https://t.alcy.cc/pc",
    "https://t.alcy.cc/ysmp",
    "https://t.alcy.cc/moemp",
    "https://t.alcy.cc/mp",
    "https://api.sretna.cn/api/pc.php",
    "https://img.chuyel.top/api",
    "https://www.dmoe.cc/random.php"
]

# 合法的图片 MIME 类型
ALLOWED_IMAGE_MIMES = {
    "image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp"
}

# 单图最大大小（10MB）
MAX_IMAGE_SIZE = 10 * 1024 * 1024

class ImageManager:
    """图片管理类：负责下载、保存、列出和删除图片"""
    def __init__(self, data_dir: str):
        self.imgs_folder = os.path.join(data_dir, "imgs")
        self.supported_extensions = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'}
        self._init_folder()

    def _init_folder(self):
        """初始化图片文件夹"""
        if not os.path.exists(self.imgs_folder):
            os.makedirs(self.imgs_folder)
            logger.info(f"Created images folder: {self.imgs_folder}")

    async def get_image_list(self):
        """获取本地缓存的有效图片列表"""
        try:
            files = await asyncio.to_thread(os.listdir, self.imgs_folder)
            return [f for f in files if os.path.splitext(f)[1].lower() in self.supported_extensions]
        except Exception as e:
            logger.error(f"Error getting image list: {str(e)}")
            return []

    async def delete_image(self, filename: str):
        """物理删除图片文件"""
        file_path = os.path.join(self.imgs_folder, filename)
        try:
            if os.path.exists(file_path):
                await asyncio.to_thread(os.remove, file_path)
                return True
            return False
        except Exception as e:
            logger.error(f"Error deleting image {filename}: {str(e)}")
            return False

    async def generate_and_save_image(self, url: str) -> Optional[str]:
        """从 API 下载并保存图片"""
        # 增加 User-Agent 模拟浏览器，防止部分 API 拦截
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        try:
            timeout = aiohttp.ClientTimeout(total=25, connect=10)
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(url, allow_redirects=True, max_redirects=5) as response:
                    if response.status != 200:
                        return None

                    # 校验 Content-Type
                    content_type = response.headers.get("Content-Type", "").lower().split(';')[0].strip()
                    if content_type not in ALLOWED_IMAGE_MIMES and "image" not in content_type:
                        return None

                    ext = mimetypes.guess_extension(content_type) or ".jpg"
                    filename = f"{uuid.uuid4().hex}{ext}"
                    file_path = os.path.join(self.imgs_folder, filename)

                    content = b""
                    async for chunk in response.content.iter_chunked(8192):
                        content += chunk
                        if len(content) > MAX_IMAGE_SIZE:
                            logger.error(f"Image from {url} too large.")
                            return None

                    async with file_lock:
                        async with aiofiles.open(file_path, 'wb') as f:
                            await f.write(content)
                    
                    return filename
        except Exception as e:
            logger.error(f"Error saving image from {url}: {str(e)}")
            return None

@register("astrbot_plugin_Pic", "ImNotBird", "我要看图插件", "1.6.4")
class ImagePlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.data_dir = StarTools.get_data_dir()
        self.image_manager = ImageManager(self.data_dir)
        self.max_retries = 2

    @filter.message_type(EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent) -> MessageEventResult:
        """监听触发词"""
        text = event.message_str.strip()
        if text == "我要看图":
            # 开启异步任务处理，不阻塞主线程
            return await self.handle_image_request(event)
        
        return event.ignore()

    async def handle_image_request(self, event: AstrMessageEvent) -> MessageEventResult:
        """处理图片获取、发送和清理的逻辑"""
        try:
            # 1. 立即反馈，提升用户体验
            await event.send(MessageEventResult().message([Plain("🚀 正在寻找精美图片，请稍候...")]))
            
            failed_urls = set()
            filename = None
            
            # 2. 多次重试不同的 API 
            for attempt in range(self.max_retries + 1):
                available_urls = [url for url in IMAGE_API_URLS if url not in failed_urls]
                if not available_urls:
                    break
                
                selected_api_url = random.choice(available_urls)
                filename = await self.image_manager.generate_and_save_image(selected_api_url)
                
                if filename:
                    break
                failed_urls.add(selected_api_url)

            if not filename:
                await event.send(MessageEventResult().message([Plain("❌ 哎呀，所有图源都暂时无法访问，请稍后再试。")]))
                return event.ignore()

            # 3. 构建路径并发送
            image_path = os.path.abspath(os.path.join(self.image_manager.imgs_folder, filename))
            
            if os.path.exists(image_path):
                # 构造图片消息
                result = MessageEventResult().message([Image.from_file(image_path)])
                await event.send(result)
                
                # 4. 延迟删除：等待 5 秒确保发送引擎已读取文件
                await asyncio.sleep(5)
                await self.image_manager.delete_image(filename)
            
            return event.ignore() 

        except Exception as e:
            logger.error(f"Request handling failed: {str(e)}")
            return event.ignore()

    async def terminate(self):
        """插件卸载或重启时执行清理工作"""
        image_files = await self.image_manager.get_image_list()
        for f in image_files:
            await self.image_manager.delete_image(f)
        logger.info("ImagePlugin temporary files cleared.")
