import asyncio
import datetime
import time
from typing import List, Tuple, Callable, Awaitable
from zoneinfo import ZoneInfo

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api import logger, AstrBotConfig
from astrbot.core.message.message_event_result import MessageChain

from .utils import TimeUtils
from .wmxy_client import WanxiaoClient, RoomResult


def get_electricity_and_water_value(room: RoomResult) -> list[float]:
    electricity_odd = 0.0
    water_odd = 0.0
    for i in room.detaillist:
        if i.businesstype == '0':
            electricity_odd = float(i.odd)
        elif i.businesstype == '1':
            water_odd = float(i.odd)

    return [electricity_odd, water_odd]


class PollerTextBuilder:
    def __init__(self, limit_electricity, limit_water):
        self.limit_electricity = limit_electricity
        self.limit_water = limit_water

    def get_current_time(self) -> str:
        current = datetime.datetime.now(tz=ZoneInfo('Asia/Taipei'))
        return current.strftime("%Y-%m-%d %H:%M:%S")

    def _get_room_electricity_and_water_text(self, room: RoomResult):
        electricity_odd, water_odd = get_electricity_and_water_value(room)
        return [
            f'⚡电费: {electricity_odd}度 {"✅" if electricity_odd > self.limit_electricity else "⚠️"}',
            f'💧水费: {water_odd}吨 {"✅" if water_odd > self.limit_water else "⚠️"}'
        ]

    def active_room_limit_notify(self, rooms: List[RoomResult]):
        text = '⚠️监测到有房间的电费/水费不足！\n\n'

        for i in rooms:
            text += f'🏠 {i.roomfullname}\n'

            temp = self._get_room_electricity_and_water_text(i)
            text += f'      {temp[0]}\n'
            text += f'      {temp[1]}\n'

        text += f'\n🚧电费阈值: {self.limit_electricity}度\n🚧水费阈值: {self.limit_water}吨\n'
        text += f'🕙当前时间: {self.get_current_time()}'

        return text

    def passive_room_list(self, rooms: List[RoomResult], data_time: float):
        text = '🔍您账号下绑定的所有房间信息\n\n'

        for i in rooms:
            text += f'🏠 {i.roomfullname}\n'

            temp = self._get_room_electricity_and_water_text(i)
            text += f'      {temp[0]}\n'
            text += f'      {temp[1]}\n'

        text += f'\n🚧电费阈值: {self.limit_electricity}度\n🚧水费阈值: {self.limit_water}吨\n'
        text += f'📦缓存更新时间: {TimeUtils.get_datetime_strftime_in_tz(
            datetime.datetime.fromtimestamp(data_time), "Asia/Taipei"
        )}\n'
        text += f'🕙当前时间: {self.get_current_time()}'

        return text


class PollerManager:
    def __init__(self, school_id: str, student_id: str, config: AstrBotConfig,
                 send_func: Callable[[str, MessageChain], Awaitable[None]]):
        self.school_id = school_id
        self.student_id = student_id
        self.config = config
        self.send_func = send_func

        self.limit_electricity = config.get('limit_electricity')
        self.limit_water = config.get('limit_water')

        self.client = WanxiaoClient(school_id, student_id)
        self.text_builder = PollerTextBuilder(self.limit_electricity, self.limit_water)
        self._is_inited = False

    def __check_if_inited(self):
        if not self._is_inited:
            raise RuntimeError('请先正确初始化插件')

    async def init(self):
        self._is_inited = True

        self._shared_lock = asyncio.Lock()
        self._poller = asyncio.create_task(self.poller_main())
        self._poller_last_run: Tuple[List[RoomResult], int] = ([], 0)

    async def poller_sender(self):
        result = await self.client.get_rooms()
        self._poller_last_run = (result, time.time())

        temp = []
        for i in result:
            temp2 = get_electricity_and_water_value(i)
            if temp2[0] <= self.limit_electricity:
                temp.append(i)
                continue
            if temp2[1] <= self.limit_water:
                temp.append(i)
                continue

        logger.info('temp length: {}'.format(len(temp)))
        if len(temp) > 0:
            text = MessageChain().message(self.text_builder.active_room_limit_notify(temp))
            for i in self.config.get('umo_list'):
                await self.send_func(i, text)

    async def poller_main(self):
        try:
            while True:
                try:
                    async with self._shared_lock:
                        await self.poller_sender()
                except Exception as e:
                    logger.erorr(f'发生错误，等待 10 秒后重试：{e}')
                    await asyncio.sleep(10)
                    continue

                await asyncio.sleep(self.config.get('polling_time', 10))
        except asyncio.CancelledError:
            pass

    async def add_umo(self, umo: str):
        async with self._shared_lock:
            if umo not in self.config.get('umo_list'):
                self.config['umo_list'].append(umo)

    async def remove_umo(self, umo: str):
        async with self._shared_lock:
            if umo in self.config.get('umo_list'):
                self.config['umo_list'].remove(umo)

    async def reload(self):
        async with self._shared_lock:
            self._poller.cancel()

            self._poller = asyncio.create_task(self.poller_main())
            self._poller_last_run: Tuple[List[RoomResult], int] = ([], 0)

    async def force_update(self):
        async with self._shared_lock:
            await self.poller_sender()

    async def terminate(self):
        await self.client.destroy()
        self._poller.cancel()

    @property
    def cached_rooms(self) -> List[RoomResult]:
        return self._poller_last_run[0]

    @property
    def cached_time(self) -> float:
        return self._poller_last_run[1]


@register("astrbot_plugin_perfect_campus_zqu_query", "sctop", "完美校园水电费轮询插件，针对肇庆学院（ZQU）特化", "1.0.0")
class PerfectCampusZquQuery(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context, config)
        self.config = config
        self._is_inited = False

    async def initialize(self):
        """可选择实现异步的插件初始化方法，当实例化该插件类之后会自动调用该方法。"""
        school_id = self.config.get('school_id')
        student_id = self.config.get('student_id')
        if school_id == '' or student_id == '':
            logger.error('请先正确设置插件的学校ID和学号！')
            return

        self.poller = PollerManager(school_id, student_id, self.config, self.send_message_callback)
        await self.poller.init()

        self._is_inited = True

    def check_inited(self):
        if not self._is_inited:
            raise RuntimeError('请先正确初始化插件后再使用！')

    @filter.command_group('wmxy')
    async def wmxy(self):
        pass

    @filter.permission_type(filter.PermissionType.ADMIN)
    @wmxy.command('on')
    async def on(self, event: AstrMessageEvent):
        try:
            self.check_inited()

            await self.poller.add_umo(event.unified_msg_origin)
            yield event.plain_result(f'✅ 已为本群【启用】完美校园提醒功能')
        except Exception as e:
            yield event.plain_result(f'🚨 执行失败！请稍后重试。\n错误原因：{e}')
        finally:
            event.stop_event()

    @filter.permission_type(filter.PermissionType.ADMIN)
    @wmxy.command('off')
    async def off(self, event: AstrMessageEvent):
        try:
            self.check_inited()

            await self.poller.remove_umo(event.unified_msg_origin)
            yield event.plain_result(f'✅ 已为本群【关闭】完美校园提醒功能')
        except Exception as e:
            yield event.plain_result(f'🚨 执行失败！请稍后重试。\n错误原因：{e}')
        finally:
            event.stop_event()

    @wmxy.command('check', alias={'list'})
    async def check(self, event: AstrMessageEvent):
        try:
            self.check_inited()

            if event.unified_msg_origin not in self.config.get('umo_list'):
                event.stop_event()
                return

            text = self.poller.text_builder.passive_room_list(self.poller.cached_rooms, self.poller.cached_time)
            yield event.plain_result(text)
        except Exception as e:
            yield event.plain_result(f'🚨 执行失败！请稍后重试。\n错误原因：{e}')
        finally:
            event.stop_event()

    @filter.permission_type(filter.PermissionType.ADMIN)
    @wmxy.command('force_update')
    async def force_update(self, event: AstrMessageEvent):
        try:
            self.check_inited()

            yield event.plain_result(f'⏳ 正尝试强制更新……')
            await self.poller.force_update()
            yield event.plain_result(f'✅ 已强制触发数据更新')
        except Exception as e:
            yield event.plain_result(f'🚨 执行失败！请稍后重试。\n错误原因：{e}')
        finally:
            event.stop_event()

    @filter.permission_type(filter.PermissionType.ADMIN)
    @wmxy.command('reload')
    async def reload(self, event: AstrMessageEvent):
        try:
            self.check_inited()

            yield event.plain_result(f'⏳ 正尝试重载插件主要 asyncio Task')
            await self.poller.reload()
            yield event.plain_result(f'✅ 已强制重载插件主要 asyncio Task')
        except Exception as e:
            yield event.plain_result(f'🚨 执行失败！请稍后重试。\n错误原因：{e}')
        finally:
            event.stop_event()

    async def send_message_callback(self, umo: str, message_chain: MessageChain):
        for i in range(10):
            try:
                await self.context.send_message(umo, message_chain)
                return
            except Exception as e:
                logger.error(f'无法发送消息到 {umo} (第{i + 1}次 ,MessageChain {message_chain}): {e}')
        logger.error(f'无法发送信息到 {umo} ，已取消本次发送')

    async def terminate(self):
        """可选择实现异步的插件销毁方法，当插件被卸载/停用时会调用。"""
        await self.poller.terminate()
