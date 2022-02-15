# Fuwa Gateway

The gateway implementation for the fuwa eco-system

### Example
```py
import asyncio
import logging

from fuwa.gateway.connection import GatewayConnection
from fuwa.gateway.intents import IntentsFlags


logging.basicConfig(level=logging.INFO)
intents = IntentsFlags(
    guilds=True,
    guild_messages=True
)

async def launch():
    connection = GatewayConnection(
        "Your Bot Token Here",
        intents
    )

    await connection.open_connection("wss://gateway.discord.gg/") # you would preferrably
    # get this gateway url with fuwa-http

    async def my_event_handler(event_data: dict):
        content = event_data["content"]
        print(content)

    connection.add_event_handler("MESSAGE_CREATE", my_event_handler)

loop = asyncio.get_event_loop()
loop.run_until_complete(launch())
loop.run_forever()
```

You may think this is quite over the top for a gateway handler, however keep in mind, you are looking at the raw gateway library. If you wanted to, you could just use the Fuwa Gateway, however most of the time, you would use one of the other Fuwa packages along side this, such as the `command_framework`. Most of the packages will link into Fuwa Gateway, meaning you won't usually have to create your own event handlers. Also, the soon to come `bundler`, will assist you in creating Fuwa Bots.

### Install
```bash
pip install fuwa[gateway]
```