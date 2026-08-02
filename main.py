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

# 图源地址池
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

# 允许的图片MIME类型
ALLOWED_IMAGE_MIMES = {
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp"
}

@register("pic_plugin", "ABird", "随机看图插件，严格匹配指令「我要看图」", "1.0.0")
class PicPlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.cache_dir = "./pic_cache"
        os.makedirs(self.cache_dir, exist_ok=True)

    async def download_image(self, session: aiohttp.ClientSession, url: str) -> Optional[str]:
        """下载图片到本地缓存"""
        try:
            resp = await session.get(url, timeout=aiohttp.ClientTimeout(total=10))
            if resp.status != 200:
                return None

            mime_type = resp.headers.get("Content-Type", "")
            if mime_type.split(";")[0] not in ALLOWED_IMAGE_MIMES:
                return None

            ext = mimetypes.guess_extension(mime_type) or ".jpg"
            save_path = os.path.join(self.cache_dir, f"{uuid.uuid4()}{ext}")

            async with file_lock:
                async with aiofiles.open(save_path, "wb") as f:
                    await f.write(await resp.read())
            return save_path
        except Exception as e:
            logger.warning(f"图片下载失败: {e}")
            return None

    async def clean_cache(self, path: str):
        """异步删除缓存文件"""
        try:
            if os.path.exists(path):
                os.remove(path)
        except Exception as e:
            logger.debug(f"缓存清理异常: {e}")

    @event_message_type(EventMessageType.GROUP_MESSAGE, EventMessageType.PRIVATE_MESSAGE)
    async def on_message(self, event: AstrMessageEvent) -> Optional[MessageEventResult]:
        # 严格全匹配指令，必须完全等于「我要看图」才触发
        msg_text = event.get_plaintext().strip()
        if msg_text != "我要看图":
            return None

        yield event.plain_result("好的，正在为你准备图片...")

        selected_api = random.choice(IMAGE_API_URLS)
        async with aiohttp.ClientSession() as session:
            img_path = await self.download_image(session, selected_api)

        if not img_path:
            yield event.plain_result("获取图片失败，请稍后再试")
            return

        yield event.image_result(img_path)
        yield event.plain_result("图片已送达")

        # 发送完毕后清理缓存
        asyncio.create_task(self.clean_cache(img_path))
    "image/png",
    "image/gif",
    "image/webp",
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

@register("astrbot_plugin_Pic", "ImNotBird", "我要看图", "1.6.3", "https://github.com/ImNotBird/astrbot_plugin_Pic")
class ImagePlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.image_manager = image_manager
        # 配置重试参数
        self.max_retries = 2  # 失败后重试2次，总共3次尝试

    @event_message_type(EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent) -> MessageEventResult:
        """处理所有消息事件"""
        try:
            text = event.message_str.lower()
            if "我要看图" in text:
                await event.send(event.plain_result("好的，正在为你准备图片..."))
                return await self.handle_image_request(event)
        except Exception as e:
            logger.error(f"Message handler error: {str(e)}")
            return event.plain_result(f"插件异常: {str(e)}")

    async def handle_image_request(self, event: AstrMessageEvent) -> MessageEventResult:
        """异步处理图片请求全流程（带自动切换图源重试）"""
        try:
            failed_urls = set()
            filename = None
            
            # 循环尝试获取图片，最多max_retries+1次
            for attempt in range(self.max_retries + 1):
                # 从可用图源中排除已经失败的
                available_urls = [url for url in IMAGE_API_URLS if url not in failed_urls]
                if not available_urls:
                    logger.error("All image APIs have failed")
                    break
                
                # 随机选择一个可用图源
                selected_api_url = random.choice(available_urls)
                logger.info(f"Attempt {attempt+1}/{self.max_retries+1}: Selected image API: {selected_api_url}")

                # 尝试下载图片
                filename = await self.image_manager.generate_and_save_image(selected_api_url)
                if filename:
                    break  # 下载成功，退出重试循环
                
                # 下载失败，记录并继续重试
                failed_urls.add(selected_api_url)
                logger.warning(f"Attempt {attempt+1} failed with API: {selected_api_url}")

            # 所有尝试都失败
            if not filename:
                return event.plain_result(f"所有图源都获取失败了（已重试{self.max_retries}次），请稍后再试")

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
