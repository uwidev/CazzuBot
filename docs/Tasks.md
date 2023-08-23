# Tasks
A task is something meant to happen in the future. They are assigned to functions within a cog with the `@tasks.loop()` decorator. This task will be ran on every interval based on the passed arguments.

For one time tasks at specific times, it's recommended to check at intervals of the lowest denominator, and register a `TaskEntry` to the database, with 