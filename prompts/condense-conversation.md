Compress the conversation into a short fact sheet. Output only bullet points.

Format: one fact per line, starting with "* ". No headline. No intro. No closing line.

Good:
* Pilot is Marcus, dislikes being called commander
* Flies a Drake Cutlass Black, sold his Aurora for it
* Saving for an Idris with his friend Tobias, about 12 million so far
* Refuses mining work

Bad (never do this):
* The user asked about cargo status
* The assistant said it does not have access to the manifest
* The wingman_starhead server was activated
* The available tools are mcp_get_ships, mcp_get_shops

Keep names, ships, orgs, preferences, plans and results. Drop commands that were
just executed, tool names, and anything the assistant could not do. Merge related
facts. Be short — about one tenth of the conversation. Output nothing if there is
nothing worth keeping.
