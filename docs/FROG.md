The purpose of this document is to formally layout the various types of frog
and their statuses and outcomes.


Frog system
-----------

Instead of merely a frog count, users will now have an inventory. This
inventory can hold many things, frogs included. When a frog is captured, it is
added to their inventory. Consumption is based on if they have it in their
inventory and how much they have.


Some rules
----------

 -  When consuming multiple stacks of items, or the same item when a status
    is ongoing, only the duration is increased, not for a stronger status.
     -  It's possible we may want a “stronger” stacking status in the future.
        We need some kind on infrastructure to define what happens when you
        reapply a status that already exists on a user.
     -  It's possible we need to generalize this stacking feature not only to
        user statuses, but to any status. Statuses might apply to something
        like the way frogs spawn (i.e. decreased interval of spawning of
        frogs). Not too sure how to proceed here.


Frog Types
----------

### Basic Frog

The most normalest frog of them all.

Asset: frog-basic.png as Emoji
Spawn Weight: 1000

On Capture: Acquire x1 Basic Frog
On Consumption: Nothing. Consuming it grants nothing.

### Pog Frog

A frog with a pog.

Asset: frog-pog.png as Emoji
Spawn Weight: 200

On Capture: Acquire x1 Pog Frog
On Consumption: For the next hour, there's a 1% chance
for the bot to react to this user's messages with the froggers emoji. 10 second
cooldown per react.

### Froggers Frog

A frog with a poggers.

Asset: frog-froggers.png as Emoji
Spawn Weight: 50

On Capture: Acquire x1 Froggers Frog
On Consumption: For the next hour, there's a 7% chance
for the bot to react to this user's messages with the froggers emoji. 10 second
cooldown per react.

### Classy Frog

A frog with rather refined tastes.

Asset: frog-classy.png as Emoji
Spawn Weight: 200

On Capture: Acquire x1 Classy Frog
On Consumption: User acquires a specific role for 3
hours. On dev guild this role is 1542294599358353430. On production this role
is 1542293782588952696.

### Cluster Frog

Be careful with this one… she's… spawning!

Asset: frog-cluster.png as Emoji
Spawn Weight: 300

On Capture: Cannot be captured. Instead immediately (with a delay to prevent
rate limiting) spawn 2 to 10 Basic Frogs, weighted so small bursts are the
common case and 10 is a ~10% jackpot. The burst scatters across the text
channels in the caught channel's category, within 2 channel positions either
side of it.
On Consumption: Nothing. User should not be able to acquire this item, this
item should not exist and does not need to be defined.


Season rollover
---------------

Seasons are quarters. On the 1st of Jan/Apr/Jul/Oct at 00:00 UTC every frog in
the server **freezes in place**: each species' normal stack becomes its frozen
stack (``frog:<species>:normal -> frog:<species>:frozen``), merging into
whatever the member already holds frozen. Species identity survives — what does
not survive is value.

 -  Frozen frogs are **trophies**: they cannot be consumed
    (`/inventory consume` refuses them).
 -  ``/inventory thaw <slot> [amount]`` is the only way out, rolled **per
    unit**: 50% restores the species' normal frog (its status effect again,
    re-freezing at the next rollover if unused), 50% leaves **Frog Remains**
    (id ``remains`` — a memorial item that grants nothing).
 -  Cluster has no item, so nothing freezes for it, and Frog Remains is not a
    frog — it never freezes and never thaws.

The rule of thumb for members: consume what you want before the rollover, or
gamble on the thaw after.
