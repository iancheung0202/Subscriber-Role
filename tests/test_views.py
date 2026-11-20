import asyncio

import views


class Response:
    def __init__(self, done):
        self.done, self.sent = done, []

    def is_done(self):
        return self.done

    async def send_message(self, embed, ephemeral):
        self.sent.append(embed.description)


class Interaction:
    def __init__(self, done=False):
        self.response = Response(done)


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
