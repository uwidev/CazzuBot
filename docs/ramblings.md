effects
items
frog species
on spawn
on catch
on consume
events

need a way to differentiate between the effects from items and the effects
objects themselves

items themselves have an effect

and there also exists the effects concepts, effects declarations

the issue is that by saying “effects”, it's ambiguous what we really mean

yes, you could have a specifier i.e. item effects or user effects, but what if
an user effect is the result from an item effect? it's just confusing.

so we need to change the language here to something else.

triggers? items have triggers? then they can be activated when you consume
them? but then a trigger… definitely not trigger, there's overlap in meaning
there as well, the on event trigger this action thing

outcome? consuming an item results in this outcome. that could work.

rename "effects" to "status", as effects is a catch all for everything (i.e.
cause and effect, visual effects, etc.)

status need more isolated and atomic definitions.

items pull from in which they wish to compose outcomes

cluster frog's "on spawn" shouldn't be an effect (or rather, a status), it's
merely it's behavior.

<!-- vim: set textwidth=80 : -->
