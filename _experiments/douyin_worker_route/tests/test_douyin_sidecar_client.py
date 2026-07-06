import unittest

from pipeline.douyin_sidecar_client import SidecarFetcher, _method_to_event


class FakeSink:
    def __init__(self) -> None:
        self.events = []
        self.meta = []

    def emit(self, **kwargs):
        self.events.append(kwargs)

    def set_room_meta(self, live_id: str, nickname: str) -> None:
        self.meta.append((live_id, nickname))


class SidecarEventMappingTests(unittest.TestCase):
    def test_maps_chat_message(self) -> None:
        event = _method_to_event(
            {
                "method": "WebcastChatMessage",
                "roomId": "room-1",
                "user": {"id": "u1", "nickname": "观众"},
                "content": "多少钱",
            },
            "web-rid",
        )

        self.assertEqual(event["event_type"], "chat")
        self.assertEqual(event["room_id"], "room-1")
        self.assertEqual(event["live_id"], "web-rid")
        self.assertEqual(event["user_name"], "观众")
        self.assertEqual(event["content"], "多少钱")

    def test_maps_like_message_with_extra_count(self) -> None:
        event = _method_to_event(
            {
                "method": "WebcastLikeMessage",
                "user": {"idStr": "u2", "nickName": "小明"},
                "count": 7,
            },
            "web-rid",
            "room-fallback",
        )

        self.assertEqual(event["event_type"], "like")
        self.assertEqual(event["room_id"], "room-fallback")
        self.assertEqual(event["content"], "7")
        self.assertEqual(event["extra"], {"count": 7})

    def test_maps_member_social_fansclub_and_stat(self) -> None:
        member = _method_to_event({"method": "WebcastMemberMessage"}, "rid")
        social = _method_to_event({"method": "WebcastSocialMessage"}, "rid")
        fans = _method_to_event({"method": "WebcastFansclubMessage", "content": "加入粉丝团"}, "rid")
        stat = _method_to_event(
            {"method": "WebcastRoomUserSeqMessage", "total": 12, "totalPvForAnchor": 345},
            "rid",
        )

        self.assertEqual(member["event_type"], "member")
        self.assertEqual(member["content"], "进入直播间")
        self.assertEqual(social["event_type"], "social")
        self.assertEqual(fans["event_type"], "fansclub")
        self.assertEqual(stat["event_type"], "stat")
        self.assertEqual(stat["content"], "current=12;total_pv=345")
        self.assertEqual(stat["extra"], {"current": 12, "total_pv": 345})

    def test_maps_room_stats_message_from_real_sidecar_shape(self) -> None:
        event = _method_to_event(
            {
                "common": {"method": "WebcastRoomStatsMessage", "roomId": "7658209366805777188"},
                "method": "WebcastRoomStatsMessage",
                "displayValue": "8164427",
                "total": "2671",
            },
            "127453393722",
        )

        self.assertEqual(event["event_type"], "stat")
        self.assertEqual(event["room_id"], "7658209366805777188")
        self.assertEqual(event["content"], "current=2671;total_pv=8164427")
        self.assertEqual(event["extra"], {"current": "2671", "total_pv": "8164427"})

    def test_ignores_unknown_or_malformed_messages(self) -> None:
        self.assertIsNone(_method_to_event({}, "rid"))
        self.assertIsNone(_method_to_event({"method": "WebcastUnknownMessage"}, "rid"))


class SidecarFetcherMessageTests(unittest.TestCase):
    def test_on_message_updates_meta_and_emits_event(self) -> None:
        sink = FakeSink()
        metadata = []
        fetcher = SidecarFetcher("123", sink, on_metadata=lambda nick, avatar: metadata.append((nick, avatar)))

        fetcher._on_message(
            None,
            '{"method":"WebcastChatMessage","livename":"主播A","avatarThumb":"https://a.test/a.jpg",'
            '"user":{"nickname":"观众"},"content":"来了"}',
        )

        self.assertEqual(sink.meta, [("123", "主播A")])
        self.assertEqual(fetcher.anchor_nick, "主播A")
        self.assertEqual(fetcher.anchor_avatar, "https://a.test/a.jpg")
        self.assertEqual(metadata, [("主播A", "https://a.test/a.jpg")])
        self.assertEqual(len(sink.events), 1)
        self.assertEqual(sink.events[0]["event_type"], "chat")

    def test_system_live_status_updates_state(self) -> None:
        statuses = []
        fetcher = SidecarFetcher("123", FakeSink(), on_status=statuses.append)

        fetcher._on_message(
            None,
            '{"type":"system","event":"live_status","live":true,"room_id":"999","message":"直播间已开播"}',
        )

        self.assertTrue(fetcher.is_live)
        self.assertEqual(fetcher.room_id, "999")
        self.assertEqual(fetcher.page_state, "room")
        self.assertEqual(statuses[0].message, "直播间已开播")


if __name__ == "__main__":
    unittest.main()
