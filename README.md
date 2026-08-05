## CazzuBot
This is the bot that runs [Club Cirno](https://discord.gg/club-cirno).

Primary features are as follows.
- Experience scoring algorithm to evaluate user activity
- Ranked roles based on experience
- Token (frog) spawning system to encourage activity
- Leaderboards for both experience and tokens
- Seasonal resets and lifetime tracking for all features listed above
- Other utility to batch work for the server

On the technical side of things:
- Containerized with docker
- Asynchronous PostgreSQL
- Has support for multiple guilds, but experiemental and has not been tested
  - Not a planned feature, more so good practices

The bot may not initialize its own database. If you try to run the bot yourself, you may need to manually create it. I may or may not support it, as I wrote this bot specifically for Club Cirno and learning purposes.
