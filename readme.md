# About DTOC

DTOC (stands for D.* TOrrent Client) is an experimental BitTorrent client written in Python3 that supports LNDP (stands for Local Network Download Protocol) and was developed as a part of my final year BE project. It uses [twisted](https://twistedmatrix.com/trac/) framework.

[Click here](https://youtu.be/J84ngDP2OTE) to see DTOC in action. Will **not** open in new tab.

***Note*** This is **not** a BitTorrent client you should   use instead of (your favorite BitTorrent client here). DTOC is very primitive and lacks features
like PEX, DHT and magnet links, and its not under active development. It was developed as a proof of concept for LNDP.

Even though its useless for non-developers, my developer friends are free to modify modules like UDP Tracker to use in their project if they don't want to start from scratch(like I had to).

# About LNDP
BitTorrent protocol without any extension doesn't consider local network topology. That is if there are two people in the same network downloading a same file, there are good chances that both people download same pieces from the Internet. When BitTorrent clients support LNDP users downloading a same file collaborates. It is like one user saying "Hey why don't you download file x and I will download file Y and then we will share it with each other." except in LNDP they collaborate on pieces. This way even if bandwidth is being throttled by gateway router, if more than one user is downloading a same file, they can achieve a speedup.

LNDP protocol is described [here.](pdfs/protocol.pdf)
