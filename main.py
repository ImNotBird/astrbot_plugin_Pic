import os
import asyncio
import logging
import aiofiles
import aiohttp
import random
import uuid
import mimetypes
from typing import List, Optional
from astrbot.api.star import Context, Star, register
from astrbot.api.event import AstrMessageEvent, MessageEventResult
from astrbot.api.event.filter import event_message_type, EventMessageType
from astrbot.api.message_components import *

logger = logging.getLogger(__name__)

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
    "https://api.sretna.cn/api/pc.php",
    "https://api.yppp.net/api.php",
    "https://api.yppp.net/pc.php",
    "https://www.dmoe.cc/random.php",
    "https://t.alcy.cc/mp"
]

# 合法的图片Content-Type
ALLOWED_IMAGE_MIMES = {
    "image/jpeg"，
    "image/png"，
    "image/gif"，
    "image/webp"，
    "image/bmp"
}

class ImageManager:
    """图片管理类"""
    def __init__(self):
        self.imgs_folder = "imgs"
        self.supported_extensions = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'}
        self._init_folder()

    def _init_folder(self):
        """初始化图片文件夹"""
        if not os.path.exists(self.imgs_folder):
            os.makedirs(self.imgs_folder)
            logger.info("Created images folder")

    async def get_image_list(self):
        """获取有效图片列表"""
        async with file_lock:
            try:
                files = await asyncio.to_thread(os.listdir, self.imgs_folder)
                return [f for f in files if os.path.splitext(f)[1].lower() in self.supported_extensions]
            except Exception as e:
                logger.error(f"Error getting image list: {str(e)}")
                return []

    async def delete_image(self, filename: str):
        """安全删除图片文件"""
        async with file_lock:
            file_path = os.path.join(self.imgs_folder, filename)
            try:
                if os.path.exists(file_path):
                    await asyncio.to_thread(os.remove, file_path)
                    logger.info(f"Deleted image: {filename}")
                    return True
                logger.warning(f"Attempted to delete non-existent file: {filename}")
                return False
            except Exception as e:
                logger.error(f"Error deleting image {filename}: {str(e)}")
                return False

    async def generate_and_save_image(self, url) -> Optional[str]:
        """
        下载并保存图片，自动处理重定向、校验图片合法性、匹配正确后缀
        返回：成功返回文件名，失败返回None
        """
        async with file_lock:
            try:
                # 配置会话：强制跟随重定向，设置合理超时
                timeout = aiohttp.ClientTimeout(total=20, connect=10)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(url, allow_redirects=True, max_redirects=5) as response:
                        # 校验响应状态
                        response.raise_for_status()
                        logger.info(f"Request {url} completed, status: {response.status}")

                        # 校验返回内容是否为图片
                        content_type = response.headers.get("Content-Type", "").lower()
                        if content_type not in ALLOWED_IMAGE_MIMES:
                            logger.error(f"Invalid Content-Type: {content_type}, not a valid image")
                            return None

                        # 自动匹配正确的文件后缀
                        ext = mimetypes.guess_extension(content_type)
                        if not ext or ext.lower() not in self.supported_extensions:
                            ext = ".jpg"  # 兜底后缀
                        
                        # 生成唯一文件名
                        filename = f"{uuid.uuid4().hex}{ext}"
                        file_path = os.path.join(self.imgs_folder, filename)

                        # 异步写入文件
                        content = await response.read()
                        async with aiofiles.open(file_path, 'wb') as f:
                            await f.write(content)
                        
                        logger.info(f"Successfully saved image: {filename}, size: {len(content)} bytes")
                        return filename

            except aiohttp.ClientError as e:
                logger.error(f"HTTP Request Failed for {url}: {str(e)}")
                return None
            except Exception as e:
                logger.error(f"Unexpected error saving image from {url}: {str(e)}")
                return None

image_manager = ImageManager()

@register("astrbot_plugin_Pic", "ImNotBird", "我要看图", "1.6", "https://github.com/ImNotBird/astrbot_plugin_Pic")
class ImagePlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.image_manager = image_manager

    @event_message_type(EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent) -> MessageEventResult:
        """处理所有消息事件"""
        try:
            text = event.message_str.lower()
            # 修改触发词为“我要看图”
            if "我要看图" in text:
                await event.send(event.plain_result("好的，正在为你准备图片..."))
                return await self.handle_image_request(event)
        except Exception as e:
            logger.error(f"Message handler error: {str(e)}")
            return event.plain_result(f"插件异常: {str(e)}")

    async def handle_image_request(self, event: AstrMessageEvent) -> MessageEventResult:
        """异步处理图片请求全流程"""
        try:
            # 随机选择图源
            selected_api_url = random.choice(IMAGE_API_URLS)
            logger.info(f"Selected image API: {selected_api_url}")

            # 下载图片
            filename = await self.image_manager.generate_and_save_image(selected_api_url)
            if not filename:
                return event.plain_result("图片获取失败了，请稍后再试")

            # 构建图片消息
            image_path = os.path.join(self.image_manager.imgs_folder, filename)
            message_chain = event.make_result().file_image(image_path)
            
            # 发送图片
            try:
                await event.send(message_chain)
                logger.info(f"Image sent successfully: {filename}")
                
                # 延迟删除，避免发送过程中文件被删除
                await asyncio.sleep(1)
                delete_success = await self.image_manager.delete_image(filename)
                return event.plain_result("图片已送达") if delete_success \
                    else event.plain_result("图片已发送，但缓存清理遇到了小问题")

            except Exception as e:
                logger.warning(f"Send image failed for {filename}: {str(e)}")
                await self.image_manager.delete_image(filename)  
                return event.plain_result("网络波动，图片发送失败")

        except Exception as e:
            logger.error(f"Request handling failed: {str(e)}")
            return event.plain_result("处理请求时发生错误，请联系管理员")

    async def terminate(self):
        """插件停止时清理所有缓存图片"""
        try:
            image_files = await self.image_manager.get_image_list()
            if image_files:
                await asyncio.gather(*(self.image_manager.delete_image(f) for f in image_files))
            logger.info("Plugin terminated, cleaned up %d cached images", len(image_files))
        except Exception as e:
            logger.error(f"Cache cleanup failed: {str(e)}")
