from core.command_registry import install_canonical_command_registry


# Install once when the cogs package is first imported. bot.py has already
# registered its top-level commands by then, and extension loading happens before
# the normal Discord sync, so the registry sees both legacy bot.py commands and
# all Cog commands at the synchronization boundary.
install_canonical_command_registry()
