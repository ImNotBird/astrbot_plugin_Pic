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

file_lock = asyncio.Lock()

# 保持原有的 API 地址
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
    "image/jpeg", "image/png", "image/gif", "image/webp", "image/bmp"
}

MAX_IMAGE_SIZE = 10 * 1024 * 1024

class ImageManager:
    """图片管理类"""
    def __init__(self, data_dir: str):
        self.imgs_folder = os.path.join(data_dir, "imgs")
        self.supported_extensions = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'}
        self._init_folder()

    def _init_folder(self):
        if not os.path.exists(self.imgs_folder):
            os.makedirs(self.imgs_folder)

    async def get_image_list(self):
        try:
            files = await asyncio.to_thread(os.listdir, self.imgs_folder)
            return [f for f in files if os.path.splitext(f)[1].lower() in self.supported_extensions]
        except Exception as e:
            logger.error(f"Error getting image list: {str(e)}")
            return []

    async def delete_image(self, filename: str):
        file_path = os.path.join(self.imgs_folder, filename)
        try:
            if os.path.exists(file_path):
                await asyncio.to_thread(os.remove, file_path)
                return True
            return False
        except Exception as e:
            logger.error(f"Error deleting image {filename}: {str(e)}")
            return False

    async def generate_and_save_image(self, url) -> Optional[str]:
        try:
            timeout = aiohttp.ClientTimeout(total=20, connect=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, allow_redirects=True, max_redirects=5) as response:
                    response.raise_for_status()
                    
                    content_type = response.headers.get("Content-Type", "").lower().split(';')[0].strip()
                    if content_type not in ALLOWED_IMAGE_MIMES:
                        return None

                    content_length = response.headers.get("Content-Length")
                    if content_length and int(content_length) > MAX_IMAGE_SIZE:
                        return None

                    ext = mimetypes.guess_extension(content_type) or ".jpg"
                    filename = f"{uuid.uuid4().hex}{ext}"
                    file_path = os.path.join(self.imgs_folder, filename)

                    content = b""
                    async for chunk in response.content.iter_chunked(8192):
                        content += chunk
                        if len(content) > MAX_IMAGE_SIZE:
                            return None

                    async with file_lock:
                        async with aiofiles.open(file_path, 'wb') as f:
                            await f.write(content)
                    
                    return filename
        except Exception as e:
            logger.error(f"Error saving image: {str(e)}")
            return None

@register("astrbot_plugin_Pic", "ImNotBird", "我要看图插件", "1.6.3")
class ImagePlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.data_dir = StarTools.get_data_dir()
        self.image_manager = ImageManager(self.data_dir)
        self.max_retries = 2

    @filter.message_type(EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent) -> MessageEventResult:
        text = event.message_str.lower()
        if "我要看图" in text:
            # 提示正在准备
            await event.send(MessageEventResult().message([Plain("好的，正在为你准备图片...")]))
            # 异步执行请求
            return await self.handle_image_request(event)
        
        return event.ignore()

    async def handle_image_request(self, event: AstrMessageEvent) -> MessageEventResult:
        try:
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
                return MessageEventResult().message([Plain(f"所有图源都获取失败了（已尝试{self.max_retries+1}次）")])

            image_path = os.path.abspath(os.path.join(self.image_manager.imgs_folder, filename))
            
            # 使用正确的链式调用构建结果
            # 注意：AstrBot 中 Image 通常支持路径参数
            result = MessageEventResult().message([Image.from_file(image_path)])
            
            try:
                await event.send(result)
                # 稍微延迟后清理
                await asyncio.sleep(2)
                await self.image_manager.delete_image(filename)
                return event.ignore() # 已经通过 send 发送，无需返回结果再次触发发送
            except Exception as e:
                logger.warning(f"Send image failed: {str(e)}")
                await self.image_manager.delete_image(filename)
                return MessageEventResult().message([Plain("网络波动，图片发送失败")])

        except Exception as e:
            logger.error(f"Request handling failed: {str(e)}")
            return MessageEventResult().message([Plain(f"发生错误: {str(e)}")])

    async def terminate(self):
        image_files = await self.image_manager.get_image_list()
        for f in image_files:
            await self.image_manager.delete_image(f)
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
        try:
            # 配置会话：强制跟随重定向，设置合理超时
            timeout = aiohttp.ClientTimeout(total=20, connect=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, allow_redirects=True, max_redirects=5) as response:
                    # 校验响应状态
                    response.raise_for_status()
                    logger.info(f"Request {url} completed, status: {response.status}")

                    # 校验返回内容是否为图片（自动剥离参数部分）
                    content_type = response.headers.get("Content-Type", "").lower().split(';')[0].strip()
                    if content_type not in ALLOWED_IMAGE_MIMES:
                        # 增加详细错误日志，帮助诊断API返回内容问题
                        preview_content = await response.text(encoding='utf-8', errors='replace')[:200]
                        logger.error(f"Invalid Content-Type: {content_type} from {url}, not a valid image. Response preview: {preview_content}")
                        return None

                    # 校验文件大小
                    content_length = response.headers.get("Content-Length")
                    if content_length and int(content_length) > MAX_IMAGE_SIZE:
                        logger.error(f"Image too large: {content_length} bytes, max allowed: {MAX_IMAGE_SIZE} bytes")
                        return None

                    # 自动匹配正确的文件后缀
                    ext = mimetypes.guess_extension(content_type)
                    if not ext or ext.lower() not in self.supported_extensions:
                        ext = ".jpg"  # 兜底后缀
                    
                    # 生成唯一文件名
                    filename = f"{uuid.uuid4().hex}{ext}"
                    file_path = os.path.join(self.imgs_folder, filename)

                    # 分块读取并写入文件，同时检查大小
                    content = b""
                    async for chunk in response.content.iter_chunked(8192):
                        content += chunk
                        if len(content) > MAX_IMAGE_SIZE:
                            logger.error(f"Image exceeded size limit during download from {url}")
                            return None

                    # 仅文件写入部分加锁，网络请求不再串行化
                    async with file_lock:
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

@register("astrbot_plugin_Pic", "ImNotBird", "我要看图", "1.6.2", "https://github.com/ImNotBird/astrbot_plugin_Pic")
class ImagePlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        # 使用框架规范的数据目录
        self.data_dir = StarTools.get_data_dir()
        self.image_manager = ImageManager(self.data_dir)
        # 配置重试参数
        self.max_retries = 2  # 失败后重试2次，总共3次尝试

    @filter.message_type(EventMessageType.ALL)
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
        
        # 非命中分支显式返回
        return event.ignore()

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
                # 修复重试次数显示bug（原来显示max_retries次，实际尝试了max_retries+1次）
                return event.plain_result(f"所有图源都获取失败了（已尝试{self.max_retries+1}次），请稍后再试")

            # 构建图片消息
            image_path = os.path.join(self.image_manager.imgs_folder, filename)
            message_chain = event.make_result().image(image_path)  # 修复：file_image 方法重命名为 image
            
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
                # 修复：逐个处理删除异常，确保一个文件删除失败不影响其他文件
                success_count = 0
                for f in image_files:
                    if await self.image_manager.delete_image(f):
                        success_count += 1
                logger.info("Plugin terminated, cleaned up %d/%d cached images", success_count, len(image_files))
            else:
                logger.info("Plugin terminated, no cached images to clean up")
        except Exception as e:
            logger.error(f"Cache cleanup failed: {str(e)}")
    "image/gif",
    "image/webp",
    "image/bmp"
}

# 单图最大大小（10MB）
MAX_IMAGE_SIZE = 10 * 1024 * 1024

class ImageManager:
    """图片管理类"""
    def __init__(self, data_dir: str):
        self.imgs_folder = os.path.join(data_dir, "imgs")
        self.supported_extensions = {'.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp'}
        self._init_folder()

    def _init_folder(self):
        """初始化图片文件夹"""
        if not os.path.exists(self.imgs_folder):
            os.makedirs(self.imgs_folder)
            logger.info("Created images folder: %s", self.imgs_folder)

    async def get_image_list(self):
        """获取有效图片列表"""
        try:
            files = await asyncio.to_thread(os.listdir, self.imgs_folder)
            return [f for f in files if os.path.splitext(f)[1].lower() in self.supported_extensions]
        except Exception as e:
            logger.error(f"Error getting image list: {str(e)}")
            return []

    async def delete_image(self, filename: str):
        """安全删除图片文件"""
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
        try:
            # 配置会话：强制跟随重定向，设置合理超时
            timeout = aiohttp.ClientTimeout(total=20, connect=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, allow_redirects=True, max_redirects=5) as response:
                    # 校验响应状态
                    response.raise_for_status()
                    logger.info(f"Request {url} completed, status: {response.status}")

                    # 校验返回内容是否为图片（自动剥离参数部分）
                    content_type = response.headers.get("Content-Type", "").lower().split(';')[0].strip()
                    if content_type not in ALLOWED_IMAGE_MIMES:
                        # 增加详细错误日志，帮助诊断API返回内容问题
                        preview_content = await response.text(encoding='utf-8', errors='replace')[:200]
                        logger.error(f"Invalid Content-Type: {content_type} from {url}, not a valid image. Response preview: {preview_content}")
                        return None

                    # 校验文件大小
                    content_length = response.headers.get("Content-Length")
                    if content_length and int(content_length) > MAX_IMAGE_SIZE:
                        logger.error(f"Image too large: {content_length} bytes, max allowed: {MAX_IMAGE_SIZE} bytes")
                        return None

                    # 自动匹配正确的文件后缀
                    ext = mimetypes.guess_extension(content_type)
                    if not ext or ext.lower() not in self.supported_extensions:
                        ext = ".jpg"  # 兜底后缀
                    
                    # 生成唯一文件名
                    filename = f"{uuid.uuid4().hex}{ext}"
                    file_path = os.path.join(self.imgs_folder, filename)

                    # 分块读取并写入文件，同时检查大小
                    content = b""
                    async for chunk in response.content.iter_chunked(8192):
                        content += chunk
                        if len(content) > MAX_IMAGE_SIZE:
                            logger.error(f"Image exceeded size limit during download from {url}")
                            return None

                    # 仅文件写入部分加锁，网络请求不再串行化
                    async with file_lock:
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

@register("astrbot_plugin_Pic", "ImNotBird", "我要看图", "1.6.2", "https://github.com/ImNotBird/astrbot_plugin_Pic")
class ImagePlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        # 使用框架规范的数据目录
        self.data_dir = StarTools.get_data_dir()
        self.image_manager = ImageManager(self.data_dir)
        # 配置重试参数
        self.max_retries = 2  # 失败后重试2次，总共3次尝试

    @filter.message_type(EventMessageType.ALL)
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
        
        # 非命中分支显式返回
        return event.ignore()

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
                # 修复重试次数显示bug（原来显示max_retries次，实际尝试了max_retries+1次）
                return event.plain_result(f"所有图源都获取失败了（已尝试{self.max_retries+1}次），请稍后再试")

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
                # 修复：逐个处理删除异常，确保一个文件删除失败不影响其他文件
                success_count = 0
                for f in image_files:
                    if await self.image_manager.delete_image(f):
                        success_count += 1
                logger.info("Plugin terminated, cleaned up %d/%d cached images", success_count, len(image_files))
            else:
                logger.info("Plugin terminated, no cached images to clean up")
        except Exception as e:
            logger.error(f"Cache cleanup failed: {str(e)}")
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

@register("astrbot_plugin_Pic", "ImNotBird", "我要看图", "1.6.1", "https://github.com/ImNotBird/astrbot_plugin_Pic")
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
