"""模拟 BatchView 转发，验证后端中继/去重/分类/导出。"""

import asyncio
import json
import urllib.request

import websockets

WS = "ws://localhost:8765"
HTTP = "http://localhost:8766"


async def fake_room(room_num: str, nickname: str) -> None:
    async with websockets.connect(WS) as ws:
        await ws.send(json.dumps({"roomNum": room_num, "roomId": f"rid-{room_num}", "nickname": nickname, "title": f"{nickname}的直播"}))
        chat = [
            {"id": "1", "method": "WebcastChatMessage", "user": {"id": "u1", "name": "张三"}, "content": "这个多少钱"},
            {"id": "2", "method": "WebcastChatMessage", "user": {"id": "u2", "name": "李四"}, "content": "上链接"},
        ]
        await ws.send(json.dumps(chat))
        # 重复发送同一批（去重应生效）
        await ws.send(json.dumps(chat))
        await ws.send(json.dumps([
            {"id": "3", "method": "WebcastGiftMessage", "user": {"id": "u3", "name": "王五"}, "gift": {"name": "玫瑰", "count": "5"}},
            {"id": "4", "method": "WebcastMemberMessage", "user": {"id": "u4", "name": "赵六"}, "content": "进入直播间"},
            {"method": "WebcastLikeMessage", "user": {"id": "u5", "name": "钱七"}, "content": "为主播点赞了(3)"},
        ]))
        await asyncio.sleep(0.3)


async def main() -> None:
    await asyncio.gather(
        fake_room("111111", "主播A"),
        fake_room("222222", "主播B"),
    )
    await asyncio.sleep(0.5)
    out = []
    out.append("=== 全部聊天导出 ===")
    out.append(urllib.request.urlopen(f"{HTTP}/export/messages.csv?category=chat").read().decode("utf-8"))
    out.append("=== 房间111111全部 ===")
    out.append(urllib.request.urlopen(f"{HTTP}/export/messages.csv?room=111111").read().decode("utf-8"))
    out.append("=== 房间111111 含分类列(detail) ===")
    out.append(urllib.request.urlopen(f"{HTTP}/export/messages.csv?room=111111&detail=1").read().decode("utf-8"))
    out.append("=== 首页(节选) ===")
    out.append(urllib.request.urlopen(f"{HTTP}/").read().decode("utf-8")[:700])
    with open("_test_out.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print("written _test_out.txt")


if __name__ == "__main__":
    asyncio.run(main())
