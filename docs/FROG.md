The purpose of this document is to formally layout the various types of frog
and their effects.


Frog system
-----------

Instead of merely a frog count, users will now have an inventory. This
inventory can hold many things, frogs included. When a frog is captured, it is
added to their inventory. Consumption is based on if they have it in their
inventory and how much they have.


Some rules
----------

 -  When consuming multiple stacks of items, or the same item when an effect is
    ongoing, only the duration is increased, not for a stronger effect.
     -  It's possible we may want a “stronger” stacking effect in the future.
        We need some kind on infrastructure to define what happens when you
        reapply an effect that already exists on a user.
     -  It's possible we need to generalize this stacking feature not only to
        user effects, but to any effect. Effects might apply to something like
        the way frogs spawn (i.e. decreased interval of spawning of frogs). Not
        too sure how to proceed here.


Frog Types
----------

### Basic Frog

The most normalest frog of them all.

Asset: frog-basic.png as Emoji
Spawn Weight: 1000

On Capture: Acquire x1 Basic Frog
On Consumption: Acquire 10 experience

### Pog Frog

A frog with a pog.

Asset: frog-pog.png as Emoji
Spawn Weight: 200

On Capture: Acquire x1 Pog Frog
On Consumption: Acquire 30 experience. For the next hour, there's a 1% chance
for the bot to react to this user's messages with the froggers emoji. 10 second
cooldown per react.

### Froggers Frog

A frog with a poggers.

Asset: frog-froggers.png as Emoji
Spawn Weight: 50

On Capture: Acquire x1 Froggers Frog
On Consumption: Acquire 300 experience. For the next hour, there's a 7% chance
for the bot to react to this user's messages with the froggers emoji. 10 second
cooldown per react.

### ### Classy Frog

A frog with rather refined tastes.

Asset: frog-classy.png as Emoji
Spawn Weight: 200

On Capture: Acquire x1 Classy Frog
On Consumption: Acquire 200 experience. User acquires a specific role for 3
hours. On dev guild this role is 1542294599358353430. On production this role
is 1542293782588952696.

### Cluster Frog

Be careful with this one… she's… spawning!

Asset: placeholder
Spawn Weight: 300

On Capture: Cannot be captured. Instead immediately (with some delay to prevent
rate limiting) spawn some number between 4 to 10 Basic Frogs randomly scattered
around some blast area centered around the spawned channel, up 2 text channels
up and down.
On Consumption: Nothing. User should not be able to acquire this item, this
item should not exist and does not need to be defined.
