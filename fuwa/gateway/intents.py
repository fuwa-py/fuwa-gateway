class IntentsFlags:
    def __init__(self, **options):
        self._bits = None

        for intent_value in options.keys():
            try:
                func = getattr(self, intent_value)

                if not options[intent_value]:
                    continue

            except AttributeError:
                raise TypeError(f"{intent_value!r} is an invalid intent")
            else:
                bits = func()
                if self._bits is None:
                    self._bits = bits
                else:
                    self._bits = self._bits | bits

    def guilds(self):
        return 1 << 0

    def guild_members(self):
        return 1 << 1

    def guild_bans(self):
        return 1 << 2

    def guild_emojis_and_stickers(self):
        return 1 << 3

    def guild_integrations(self):
        return 1 << 4

    def guild_webhooks(self):
        return 1 << 5

    def guild_invites(self):
        return 1 << 6
    
    def guild_voice_states(self):
        return 1 << 7
    
    def guild_presences(self):
        return 1 << 8
    
    def guild_messages(self):
        return 1 << 9

    def guild_message_reactions(self):
        return 1 << 10

    def guild_message_typing(self):
        return 1 << 11
    
    def direct_messages(self):
        return 1 << 12
    
    def direct_message_reactions(self):
        return 1 << 13

    def direct_message_typing(self):
        return 1 << 14
    
    def guild_scheduled_events(self):
        return 1 << 16