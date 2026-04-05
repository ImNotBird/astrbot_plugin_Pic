import os
import asyncio
import aiofiles
import aiohttp
import random
import uuid
import mimetypes
from typing import List, Optional

# 核心规范修复：从 astrbot.api 导入 logger
from astrbot.api import logger
from astrbot.api.star import Context, Star, register
# 核心规范修复：从 astrbot.api.event 导入 filter
from astrbot.api.event import AstrMessageEvent, MessageEventResult, filter
from astrbot.api.message_components import *

file_lock = asyncio.Lock()

# 随机图源列表
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

ALLOWED_IMAGE_MIMES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
    "image/bmp"
}

class ImageManager:
    """图片管理类"""
    def __init__(self):
        self.imgs_folder = "data/imgs" # 建议放在 data 目录下
        self.supported_extensions = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'}
        self._init_folder()

    def _init_folder(self):
        if not os.path.exists(self.imgs_folder):
            os.makedirs(self.imgs_folder, exist_ok=True)
            logger.info(f"Created images folder at {self.imgs_folder}")

    async def get_image_list(self):
        async with file_lock:
            try:
                files = await asyncio.to_thread(os.listdir, self.imgs_folder)
                return [f for f in files if os.path.splitext(f)[1].lower() in self.supported_extensions]
            except Exception as e:
                logger.error(f"Error getting image list: {e}")
                return []

    async def delete_image(self, filename: str):
        async with file_lock:
            file_path = os.path.join(self.imgs_folder, filename)
            try:
                if os.path.exists(file_path):
                    await asyncio.to_thread(os.remove, file_path)
                    return True
                return False
            except Exception as e:
                logger.error(f"Error deleting image {filename}: {e}")
                return False

    async def generate_and_save_image(self, url) -> Optional[str]:
        async with file_lock:
            try:
                timeout = aiohttp.ClientTimeout(total=20, connect=10)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(url, allow_redirects=True, max_redirects=5) as response:
                        response.raise_for_status()

                        content_type = response.headers.get("Content-Type", "").lower()
                        if content_type not in ALLOWED_IMAGE_MIMES:
                            logger.error(f"Invalid Content-Type: {content_type}")
                            return None

                        ext = mimetypes.guess_extension(content_type) or ".jpg"
                        filename = f"{uuid.uuid4().hex}{ext}"
                        file_path = os.path.join(self.imgs_folder, filename)

                        content = await response.read()
                        async with aiofiles.open(file_path, 'wb') as f:
                            await f.write(content)
                        
                        return filename
            except Exception as e:
                logger.error(f"Save image failed: {e}")
                return None

@register("astrbot_plugin_Pic", "ImNotBird", "我要看图插件", "1.6.4")
class ImagePlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.image_manager = ImageManager()
        self.max_retries = 2

    # 核心规范修复：使用 @filter.event_message_type 且引用 filter.EventMessageType
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        """处理所有消息事件"""
        text = event.message_str.strip()
        if "我要看图" == text:
            yield event.plain_result("好的，正在为你准备图片...")
            yield await self.handle_image_request(event)

    async def handle_image_request(self, event: AstrMessageEvent) -> MessageEventResult:
        """图片请求逻辑"""
        failed_urls = set()
        filename = None
        
        for attempt in range(self.max_retries + 1):
            available_urls = [url for url in IMAGE_API_URLS if url not in failed_urls]
            if not available_urls: break
            
            selected_api_url = random.choice(available_urls)
            filename = await self.image_manager.generate_and_save_image(selected_api_url)
            
            if filename: break
            failed_urls.add(selected_api_url)

        if not filename:
            return event.plain_result("所有图源都失效了，请稍后再试。")

        image_path = os.path.abspath(os.path.join(self.image_manager.imgs_folder, filename))
        
        try:
            # 构建并发送图片消息
            chain = Image.fromFileSystem(image_path)
            await event.send(event.make_result().message(chain))
            
            # 延迟清理缓存
            await asyncio.sleep(2)
            await self.image_manager.delete_image(filename)
            return event.plain_result("发送完成")
            
        except Exception as e:
            logger.error(f"Send failed: {e}")
            await self.image_manager.delete_image(filename)
            return event.plain_result("图片发送失败，请检查网络。")

    async def terminate(self):
        """清理所有缓存"""
        image_files = await self.image_manager.get_image_list()
        if image_files:
            tasks = [self.image_manager.delete_image(f) for f in image_files]
            await asyncio.gather(*tasks)
        logger.info("Plugin cleanup finished.")
