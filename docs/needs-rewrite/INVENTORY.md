* Inventory

This document is a rough spec for how inventory will work.

All users have a backend inventory they have accessible to them. Based on their interactions in the server, their inventory changes.

Currently, the user can capture frogs. These frogs, depending on their effects, will mutate a user's inventory. For example, capturing a normal frog will add the x1 normal frog into the capturing user's inventory.

The user can query their inventory with a slash command.

The UI will show a grid of items with an index below (or to the left with a colon separating?) with some quantity signifier. Their icon will be some emoji. So for example.

1:EMOJIx3   2:EMOJIx4

Or potentially

EMOJIx3     EMOJIx4
1           2

We will test how it looks, but for now, we'll use the latter formatting.

With this setup, the user can then do inventory modification commands. For example, they can consume items. It can be some slash command /inventory consume (INDEX) [AMOUNT]
