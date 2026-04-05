import json
import pydantic
from typing import List, Dict

import aiohttp

class RoomResultDetailListEntry(pydantic.BaseModel):
    businesstype: str # "0" = electricity, "1" = water
    """ `"0"` = electricity, `"1"` = water """
    status: str # usually is "1"

    odd: str # 剩余可用额度
    """剩余可用额度"""
    use: str # 总计支付额度
    """总计支付额度"""

    sumbuy: float # 何意味
    sumsub: float # 看不懂

class RoomResult(pydantic.BaseModel):
    detaillist: List[RoomResultDetailListEntry]
    existflag: str
    isshowsubsidy: str
    message: str # "操作成功"
    result: str
    roomfullname: str
    roomverify: str
    ver: int


class WanxiaoClient:
    BASE_URL = "https://xqh5.17wanxiao.com/smartWaterAndElectricityService/SWAEServlet"

    def __init__(self, school_id: str, student_id: str):
        self.school_id = school_id
        self.student_id = student_id

        self.session = aiohttp.ClientSession()

    async def fetch_room_data(self) -> dict:
        payload = {
            "param": json.dumps({
                "cmd": "getbindroom",
                "account": self.student_id
            }),
            "customercode": self.school_id,
            "method": "getbindroom"
        }

        async with self.session.post(self.BASE_URL, data=payload) as resp:
            data = await resp.json()

        body_raw = data.get("body", "{}")

        if isinstance(body_raw, str):
            try:
                return json.loads(body_raw)
            except json.JSONDecodeError:
                return {}
        return body_raw

    @staticmethod
    def parse_rooms(body: dict) -> List[Dict]:
        roomlist = body.get("roomlist")

        if not roomlist:
            # 单房间
            roomlist = [body]

        return roomlist

    async def get_rooms(self) -> List[RoomResult]:
        body = await self.fetch_room_data()
        temp = self.parse_rooms(body)
        return [RoomResult(**i) for i in temp]

    async def destroy(self):
        await self.session.close()