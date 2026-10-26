# Body data

`bodies.json` holds, for every planet, moon and Lagrange point of Stanton, the
centre in global kilometres, the body radius, the orbital-marker radius, the
rotation period in hours and the rotation offset, plus its named places in
body-fixed kilometres. It is derived from `Database.json` of
[Star-Citizen-Navigation](https://github.com/Valalol/Star-Citizen-Navigation)
by Valalol, MIT License, retrieved 2026-10-26.

The transformation keeps the fields the skill needs and drops the orbital
markers (OM-1 to OM-6), mining claims and cloud layers. `reach_km` is how far
from a body's centre a position still counts as "at" that body: three
orbital-marker radii, six body radii or twice the farthest named place,
whichever is larger. The entry `Stanton` with `system: true` is the frame for
open space, at the origin and without rotation.

Rotation model: a body turns `0.1 / rotation_hours` degrees per second, counted
from 2020-01-01 00:00 UTC, plus `rotation_adjust_deg`. The offsets drift with
the game: on 2026-10-26, with a current build and a checked clock, microTech
was about four degrees off (56 km at Port Tressler). The skill therefore
stores a correction per body that the user measures once at a known place
(the calibrate_position tool); the values here are the starting point.

Pyro and Nyx are not in the data yet.

MIT License, Copyright (c) Valalol: Permission is hereby granted, free of
charge, to any person obtaining a copy of this software and associated
documentation files (the "Software"), to deal in the Software without
restriction, including without limitation the rights to use, copy, modify,
merge, publish, distribute, sublicense, and/or sell copies of the Software,
and to permit persons to whom the Software is furnished to do so, subject to
the following conditions: The above copyright notice and this permission
notice shall be included in all copies or substantial portions of the
Software. THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND.
