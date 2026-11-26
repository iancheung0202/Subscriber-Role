import asyncio
import types

import views


class Response:
    def __init__(self, done, deferred=False):
        self.done, self.sent = done, []
        self.type = views.DEFERRED if deferred else None

    def is_done(self):
        return self.done

    async def send_message(self, embed, ephemeral):
        self.sent.append(embed.description)


class Interaction:
    def __init__(self, done=False, deferred=False):
        self.response = Response(done, deferred)
        self.followup = types.SimpleNamespace(send=self.response.send_message)


def test_error_reply_is_a_plain_sentence():
    interaction = Interaction()
    asyncio.run(views.send_error(interaction))
    assert interaction.response.sent == [
        f"{views.CROSS} Something went wrong. Please try again."
    ]


def test_error_reply_is_skipped_after_a_response():
    interaction = Interaction(done=True)
    asyncio.run(views.send_error(interaction))
    assert interaction.response.sent == []


def test_error_reply_follows_a_deferred_response():
    interaction = Interaction(done=True, deferred=True)
    asyncio.run(views.send_error(interaction))
    assert len(interaction.response.sent) == 1


def test_verify_link_is_sent_as_a_follow_up(monkeypatch):
    events = []

    async def name(channel_id):
        events.append("name")
        return "Channel"

    async def send(embeds, ephemeral):
        events.append("sent")
        sent.extend(embeds)

    sent, interaction = [], Interaction()
    interaction.guild_id, interaction.user = 1, types.SimpleNamespace(id=2)
    interaction.followup = types.SimpleNamespace(send=send)
    monkeypatch.setattr(views, "get_youtube_channel_name", name)
    config = {"id": 3, "yt_channel_id": "UC" + "x" * 22}
    asyncio.run(
        views.VerifyChannelSelectView.send_verification_link(interaction, config)
    )
    assert events == ["name", "sent"] and interaction.response.sent == []
    assert "state=1_2_3_" in sent[-1].description
